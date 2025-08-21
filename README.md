# Simple tools to work with yaml and json files.

## yaml-grep

Search for a string in a yaml- or json-file and show where in the structure the pattern is found

### Usage

yaml-grep.py [-h] [-e PATTERNS] [-i] [-k | -v] [--path-format {pointer,dot}] [--color {auto,always,never}] [--max-matches MAX_MATCHES] [rest ...]



## yaml-show

Show a subtree of a yaml- or json-file based on a path

### Usage

yaml-show.py [-h] [--format {auto,yaml,json}] path file


## Credit

The base of these tools were created using Chatgpt 5.0
