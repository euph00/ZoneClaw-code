#!/usr/bin/env python3
"""Stage an OpenClaw runtime with container-local trusted ownership."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    destination = Path(args.destination).resolve()
    if not source.is_dir():
        raise SystemExit(f"runtime source does not exist: {source}")
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        raise SystemExit("missing runner command")

    shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # copytree creates new files owned by the container user. OpenClaw rejects
    # executable plugins mounted from a host account with a different uid.
    shutil.copytree(source, destination, copy_function=shutil.copyfile)

    old = str(source)
    new = str(destination)
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")

    env = os.environ.copy()
    env["OPENCLAW_CONFIG_PATH"] = str(destination / "openclaw.json")
    os.execvpe(args.command[0], args.command, env)


if __name__ == "__main__":
    main()
