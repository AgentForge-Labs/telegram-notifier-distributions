from __future__ import annotations

import argparse
import json

from .auth import auth_status, login_interactive, logout


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram-notifier-auth",
        description="Authenticate the AgentForge Telegram Notifier CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Open browser login using OAuth PKCE.")
    sub.add_parser("status", help="Show auth status without revealing credentials.")
    sub.add_parser("logout", help="Revoke OAuth credentials and remove the local credential file.")
    args = parser.parse_args(argv)
    if args.command == "login":
        result = login_interactive()
    elif args.command == "logout":
        result = logout()
    else:
        result = auth_status()
    print(json.dumps(result, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
