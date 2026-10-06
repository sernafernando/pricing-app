"""Read and change the runtime settings of the ML publications store (design D19).

    python -m app.scripts.ml_publications_settings get [key]
    python -m app.scripts.ml_publications_settings set <key> <json-value> [--by NAME]

Only allow-listed keys can be read or written (`settings_store.SETTING_DEFS`). `get` prints
the EFFECTIVE value and where it comes from: `db` (a row in `ml_pub_settings`), `env` (the
default, no row), `kill_switch` or `unreadable`. Run from the `backend/` directory so the
`.env` is found. Never calls ML.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Optional, Sequence

from app.services.ml_publications import settings_store


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ml_publications_settings")
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get", help="print the effective value and its source")
    get.add_argument("key", nargs="?", help="a setting key; omit to print every setting")
    put = commands.add_parser("set", help='write a setting (the value is JSON: true, 5, ["core"])')
    put.add_argument("key")
    put.add_argument("value")
    put.add_argument("--by", dest="updated_by", default=f"cli:{getpass.getuser()}", help="recorded in updated_by")
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if args.command == "get":
        keys = [args.key] if args.key else sorted(settings_store.SETTING_DEFS)
        if args.key and args.key not in settings_store.SETTING_DEFS:
            return _fail(
                f"unknown ml_pub setting {args.key!r}; known: {', '.join(sorted(settings_store.SETTING_DEFS))}"
            )
        for key, setting in settings_store.get_settings(keys).items():
            print(f"{key} = {json.dumps(setting.value)} (source: {setting.source})")
        return 0

    if args.key not in settings_store.SETTING_DEFS:
        return _fail(f"unknown ml_pub setting {args.key!r}; known: {', '.join(sorted(settings_store.SETTING_DEFS))}")
    try:
        value = json.loads(args.value)
    except ValueError:
        return _fail(f'value {args.value!r} is not valid JSON (use true, 5, ["core"])')
    try:
        settings_store.set_setting(args.key, value, args.updated_by)
    except ValueError as exc:
        return _fail(str(exc))
    print(f"{args.key} = {json.dumps(value)} (written by {args.updated_by})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
