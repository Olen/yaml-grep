#!/usr/bin/env python3
"""
yaml-show: print a subtree from YAML/JSON by JSON Pointer path.

Examples:
  # Show everything under /foo/bar/2 from file.yaml
  ./yaml_show.py /foo/bar/2 file.yaml

  # Read YAML from stdin
  cat config.yaml | ./yaml_show.py /services/api -

Notes:
  * Path is JSON Pointer (RFC 6901): segments separated by '/', with escapes:
      "~1" -> "/",  "~0" -> "~"
    Example key literally named "a/b": pointer "/a~1b".
  * Trailing slash is allowed and ignored for convenience.
  * If PyYAML is unavailable, YAML input won’t work (install with: pip install pyyaml).
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Any, List, Union

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:
    HAVE_YAML = False


def load_data(path: str) -> Any:
    data_bytes = sys.stdin.buffer.read() if path == "-" else open(path, "rb").read()
    text = data_bytes.decode("utf-8", errors="replace")
    ext = os.path.splitext(path)[1].lower()

    if ext in (".yaml", ".yml") or (ext == "" and HAVE_YAML):
        if not HAVE_YAML:
            sys.exit("ERROR: PyYAML not installed. Install with: pip install pyyaml")
        return yaml.safe_load(text)
    if ext == ".json":
        return json.loads(text)

    # Try JSON first, then YAML as a fallback
    try:
        return json.loads(text)
    except Exception:
        if not HAVE_YAML:
            sys.exit("ERROR: Could not parse as JSON. For YAML support: pip install pyyaml")
        return yaml.safe_load(text)


def unescape_token(tok: str) -> str:
    # JSON Pointer unescape: "~1" => "/", "~0" => "~"
    return tok.replace("~1", "/").replace("~0", "~")


def parse_pointer(ptr: str) -> List[str]:
    if ptr == "" or ptr == "/":
        return []
    if not ptr.startswith("/"):
        sys.exit(f"ERROR: Path must start with '/': {ptr!r}")
    # drop leading '/', allow trailing '/', ignore empty segments (except root)
    raw = ptr[1:]
    parts = [p for p in raw.split("/") if p != ""]
    return [unescape_token(p) for p in parts]


def resolve(obj: Any, tokens: List[str]) -> Any:
    cur = obj
    for depth, tok in enumerate(tokens, 1):
        if isinstance(cur, list):
            # For lists, the token must be an integer index
            try:
                idx = int(tok)
            except ValueError:
                path_so_far = "/" + "/".join(tokens[:depth-1])
                sys.exit(f"ERROR: Expected list index at {path_so_far or '/'} "
                         f"but got key {tok!r}")
            if idx < 0 or idx >= len(cur):
                path_so_far = "/" + "/".join(tokens[:depth-1])
                sys.exit(f"ERROR: Index {idx} out of range at {path_so_far or '/'} "
                         f"(len={len(cur)})")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if tok not in cur:
                path_so_far = "/" + "/".join(tokens[:depth-1])
                # Offer a hint with nearby keys
                keys = list(cur.keys())
                hint = ""
                if keys:
                    sample = ", ".join(map(lambda k: repr(k), keys[:10]))
                    hint = f" (available keys: {sample}{'...' if len(keys)>10 else ''})"
                sys.exit(f"ERROR: Key {tok!r} not found at {path_so_far or '/'}{hint}")
            cur = cur[tok]
        else:
            path_so_far = "/" + "/".join(tokens[:depth-1])
            sys.exit(f"ERROR: Cannot descend into non-container at {path_so_far or '/'} "
                     f"(type={type(cur).__name__})")
    return cur


def dump(obj: Any, fmt: str) -> None:
    if fmt == "json" or (fmt == "auto" and not HAVE_YAML):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        return
    # YAML
    print(yaml.safe_dump(obj, sort_keys=False, allow_unicode=True))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Show a subtree from YAML/JSON by JSON Pointer path."
    )
    ap.add_argument("path", help="JSON Pointer path, e.g. /foo/bar/2")
    ap.add_argument("file", help="YAML/JSON file path or '-' for stdin")
    ap.add_argument("--format", choices=["auto", "yaml", "json"], default="auto",
                    help="Output format (default: auto -> YAML if available else JSON)")
    args = ap.parse_args()

    tokens = parse_pointer(args.path.rstrip("/"))  # allow trailing slash
    data = load_data(args.file)
    node = resolve(data, tokens)
    fmt = args.format
    dump(node, fmt)

if __name__ == "__main__":
    main()

