#!/usr/bin/env python3
"""
yaml-grep: regex search for YAML/JSON keys & values with paths.

Usage:
  yaml_grep.py [options] [-e PATTERN ...] [--] FILE
  yaml_grep.py [options] PATTERN [PATTERN ...] -- FILE
  cat file.yaml | yaml_grep.py -i 'secret.*' -

Options:
  -e PATTERN         Add a regex (can be used multiple times). If no -e is given,
                     positional PATTERN args before FILE are used.
  -i, --ignore-case  Case-insensitive regex.
  -k, --keys-only    Search keys only.
  -v, --values-only  Search values only.
  --path-format {pointer,dot}   Output path style (default: pointer).
  --color {auto,always,never}   Colorize matches (default: auto).
  --max-matches N    Stop after N total matches (0 = unlimited).

File:
  FILE is a path or "-" for stdin. YAML requires PyYAML (pip install pyyaml).
  JSON is supported with the standard library.
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from typing import Any, Iterable, List, Tuple, Union

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:
    HAVE_YAML = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Search YAML/JSON for regex patterns and show matching paths.",
        add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-e", dest="patterns", action="append", help="Regex pattern (repeatable)")
    p.add_argument("-i", "--ignore-case", action="store_true", help="Case-insensitive search")
    g = p.add_mutually_exclusive_group()
    g.add_argument("-k", "--keys-only", action="store_true", help="Search keys only")
    g.add_argument("-v", "--values-only", action="store_true", help="Search values only")
    p.add_argument("--path-format", choices=["pointer", "dot"], default="pointer",
                   help="How to display paths")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="Colorize matches")
    p.add_argument("--max-matches", type=int, default=0, help="Stop after N matches (0 = unlimited)")
    p.add_argument("rest", nargs="*", help="[PATTERN ...] -- FILE  (or use -e)")
    return p.parse_args()


def split_patterns_and_file(rest: List[str], existing_patterns: List[str] | None) -> Tuple[List[str], str]:
    """
    Accepts either:
      yaml_grep.py -e patt -e patt -- file
      yaml_grep.py patt patt -- file
      yaml_grep.py patt file
    Returns (patterns, file)
    """
    patterns = list(existing_patterns or [])
    if not rest:
        sys.exit("ERROR: You must provide a FILE (or '-') and at least one PATTERN or -e.")
    if rest[-1] == "--":
        sys.exit("ERROR: trailing '--' without FILE")
    if "--" in rest:
        idx = rest.index("--")
        pats = rest[:idx]
        file_ = rest[idx+1] if idx + 1 < len(rest) else None
        if file_ is None:
            sys.exit("ERROR: Missing FILE after '--'")
        patterns += pats
        return (patterns, file_)
    # If more than one arg and last one looks like a file, treat others as patterns
    if len(rest) >= 2 and (os.path.exists(rest[-1]) or rest[-1] == "-"):
        patterns += rest[:-1]
        return (patterns, rest[-1])
    # Only one thing: ambiguous
    if len(rest) == 1:
        sys.exit("ERROR: Provide FILE (or '-') and at least one PATTERN (or -e).")
    # Fallback: assume last is file
    patterns += rest[:-1]
    return (patterns, rest[-1])


def load_data(path: str) -> Any:
    data_bytes = sys.stdin.buffer.read() if path == "-" else open(path, "rb").read()
    text = data_bytes.decode("utf-8", errors="replace")
    # Decide by extension first
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml") or (ext == "" and HAVE_YAML):
        if not HAVE_YAML:
            sys.exit("ERROR: PyYAML not installed. Install with: pip install pyyaml")
        return yaml.safe_load(text)
    if ext == ".json":
        return json.loads(text)
    # Try JSON, then YAML
    try:
        return json.loads(text)
    except Exception:
        if not HAVE_YAML:
            sys.exit("ERROR: Could not parse as JSON. For YAML support: pip install pyyaml")
        return yaml.safe_load(text)


def is_scalar(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None


def stringify(x: Any) -> str:
    if isinstance(x, str):
        return x
    return json.dumps(x, ensure_ascii=False)


def json_pointer_escape(token: str) -> str:
    # RFC 6901 escape: "~" -> "~0", "/" -> "~1"
    return token.replace("~", "~0").replace("/", "~1")


def to_path_pointer(tokens: List[Union[str, int]]) -> str:
    parts = []
    for t in tokens:
        if isinstance(t, int):
            parts.append(str(t))
        else:
            parts.append(json_pointer_escape(t))
    return "/" + "/".join(parts)


def to_path_dot(tokens: List[Union[str, int]]) -> str:
    out = "root"
    for t in tokens:
        if isinstance(t, int):
            out += f"[{t}]"
        else:
            # simple identifier?
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t):
                out += f".{t}"
            else:
                out += f"[{json.dumps(t)}]"  # quoted key
    return out


def colorize(s: str, regexes: List[re.Pattern], enabled: bool) -> str:
    if not enabled:
        return s
    # apply all patterns; wrap matches in ANSI bold
    # To avoid nested escapes, use a single pass that merges ranges
    ranges: List[Tuple[int, int]] = []
    for rx in regexes:
        for m in rx.finditer(s):
            ranges.append((m.start(), m.end()))
    if not ranges:
        return s
    # merge overlapping ranges
    ranges.sort()
    merged = []
    cur_s, cur_e = ranges[0]
    for s0, e0 in ranges[1:]:
        if s0 <= cur_e:
            cur_e = max(cur_e, e0)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s0, e0
    merged.append((cur_s, cur_e))
    # build string with escapes
    ESC_ON = "\033[1m"
    ESC_OFF = "\033[0m"
    out = []
    last = 0
    for s0, e0 in merged:
        out.append(s[last:s0])
        out.append(ESC_ON + s[s0:e0] + ESC_OFF)
        last = e0
    out.append(s[last:])
    return "".join(out)


def search(
    obj: Any,
    tokens: List[Union[str, int]],
    regexes: List[re.Pattern],
    match_keys: bool,
    match_values: bool,
    path_fmt: str,
    color: bool,
    max_matches: int,
    out: List[str],
) -> None:
    if max_matches and len(out) >= max_matches:
        return

    # Dict
    if isinstance(obj, dict):
        for k, v in obj.items():
            # Keys
            if match_keys:
                ks = stringify(k)
                if any(rx.search(ks) for rx in regexes):
                    path = to_path_pointer(tokens + [k]) if path_fmt == "pointer" else to_path_dot(tokens + [k])
                    shown = colorize(ks, regexes, color)
                    out.append(f"{path}\t(KEY)\t{shown}")
                    if max_matches and len(out) >= max_matches:
                        return
            # Values (for scalars)
            if match_values and is_scalar(v):
                vs = stringify(v)
                if any(rx.search(vs) for rx in regexes):
                    path = to_path_pointer(tokens + [k]) if path_fmt == "pointer" else to_path_dot(tokens + [k])
                    shown = colorize(vs, regexes, color)
                    out.append(f"{path}\t(VAL)\t{shown}")
                    if max_matches and len(out) >= max_matches:
                        return
            # Recurse
            if isinstance(v, (dict, list)):
                search(v, tokens + [k], regexes, match_keys, match_values, path_fmt, color, max_matches, out)

    # List
    elif isinstance(obj, list):
        for idx, v in enumerate(obj):
            if match_values and is_scalar(v):
                vs = stringify(v)
                if any(rx.search(vs) for rx in regexes):
                    path = to_path_pointer(tokens + [idx]) if path_fmt == "pointer" else to_path_dot(tokens + [idx])
                    shown = colorize(vs, regexes, color)
                    out.append(f"{path}\t(VAL)\t{shown}")
                    if max_matches and len(out) >= max_matches:
                        return
            if isinstance(v, (dict, list)):
                search(v, tokens + [idx], regexes, match_keys, match_values, path_fmt, color, max_matches, out)

    # Scalar at root (rare)
    else:
        if match_values and is_scalar(obj):
            s = stringify(obj)
            if any(rx.search(s) for rx in regexes):
                path = "" if path_fmt == "pointer" else "root"
                shown = colorize(s, regexes, color)
                out.append(f"{path}\t(VAL)\t{shown}")


def main() -> None:
    args = parse_args()
    patterns, file_ = split_patterns_and_file(args.rest, args.patterns)
    if not patterns:
        sys.exit("ERROR: No patterns provided.")
    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        regexes = [re.compile(p, flags) for p in patterns]
    except re.error as e:
        sys.exit(f"ERROR: invalid regex: {e}")

    data = load_data(file_)

    # Determine color
    if args.color == "always":
        use_color = True
    elif args.color == "never":
        use_color = False
    else:
        use_color = sys.stdout.isatty()

    match_keys = True
    match_values = True
    if args.keys_only:
        match_values = False
    if args.values_only:
        match_keys = False

    out: List[str] = []
    search(
        data,
        tokens=[],  # root
        regexes=regexes,
        match_keys=match_keys,
        match_values=match_values,
        path_fmt=args.path_format,
        color=use_color,
        max_matches=args.max_matches,
        out=out,
    )

    for line in out:
        print(line)

    # Exit code similar to grep: 0 if matches, 1 if none
    sys.exit(0 if out else 1)


if __name__ == "__main__":
    main()

