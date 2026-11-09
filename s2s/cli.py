import argparse
import os
import sys

from .config import ConfigError, load
from .render import render_all


def main(argv=None):
    p = argparse.ArgumentParser(prog="s2s", description="Generate RouterOS 7 site-to-site configs.")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check the input file, write nothing")
    v.add_argument("config")
    g = sub.add_parser("generate", help="write one .rsc file per site")
    g.add_argument("config")
    g.add_argument("-o", "--out", default="out")
    a = p.parse_args(argv)
    try:
        cfg = load(a.config)
    except ConfigError as exc:
        print("Invalid config:\n%s" % exc, file=sys.stderr)
        return 1
    if a.cmd == "validate":
        print("OK: %d sites" % len(cfg["sites"]))
        return 0
    os.makedirs(a.out, exist_ok=True)
    for name, text in render_all(cfg).items():
        with open(os.path.join(a.out, name), "w") as fh:
            fh.write(text)
        print("wrote %s" % os.path.join(a.out, name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
