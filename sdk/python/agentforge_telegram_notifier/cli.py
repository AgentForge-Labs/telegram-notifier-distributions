"""Command-line workflows for AgentForge Telegram Notifier."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from .auth import MANAGED_ORIGIN, TelegramNotifierAuthRequired, auth_status, login_interactive, logout, resolve_credential
from .client import DEFAULT_ORIGIN, TelegramNotifierClient, TelegramNotifierError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-notifier", description="AgentForge Telegram Notifier client")
    parser.add_argument("--origin", default=os.getenv("TELEGRAM_NOTIFIER_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--source", default=os.getenv("TELEGRAM_NOTIFIER_SOURCE", ""))
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("auth", help="Manage hosted account credentials")
    auth.add_argument("action", choices=("login", "status", "logout"))
    inbox = commands.add_parser("inbox", help="Read inbound Telegram events")
    inbox.add_argument("--after")
    inbox.add_argument("--limit", type=int, default=50)
    notify = commands.add_parser("notify", help="Send a Telegram notification")
    notify.add_argument("text")
    notify.add_argument("--title", default="")
    notify.add_argument("--idempotency-key")
    notify_file = commands.add_parser("notify-file", help="Send a document or photo")
    notify_file.add_argument("file", type=Path)
    notify_file.add_argument("--photo", action="store_true")
    notify_file.add_argument("--caption", default="")
    notify_file.add_argument("--content-type", default="application/octet-stream")
    notify_file.add_argument("--idempotency-key")
    reply = commands.add_parser("reply", help="Reply to an inbound event")
    reply.add_argument("event_id")
    reply.add_argument("text")
    reply.add_argument("--title", default="")
    reply.add_argument("--idempotency-key")
    reply_file = commands.add_parser("reply-file", help="Reply with a document or photo")
    reply_file.add_argument("event_id")
    reply_file.add_argument("file", type=Path)
    reply_file.add_argument("--photo", action="store_true")
    reply_file.add_argument("--caption", default="")
    reply_file.add_argument("--content-type", default="application/octet-stream")
    reply_file.add_argument("--idempotency-key")
    download = commands.add_parser("download", help="Download a file from an inbound event")
    download.add_argument("event_id")
    download.add_argument("output", type=Path)
    return parser


def _interactive_allowed() -> bool:
    return not os.getenv("CI") and sys.stdin.isatty() and sys.stdout.isatty()


def _client(origin: str, source: str) -> TelegramNotifierClient:
    hosted = origin.rstrip("/") == MANAGED_ORIGIN
    try:
        credential = resolve_credential(required=hosted)
    except TelegramNotifierAuthRequired:
        if not hosted or not _interactive_allowed():
            raise
        login_interactive(origin=origin)
        credential = resolve_credential(required=True)
    resolved_source = source.strip() or credential.source.strip()
    if not resolved_source:
        if hosted:
            raise TelegramNotifierAuthRequired("Telegram Notifier source identity is unavailable; sign in again or pass --source.")
        resolved_source = "telegram-notifier-cli"
    kwargs: dict[str, str] = {}
    if credential.token:
        kwargs["bearer_token" if credential.kind == "oauth" else "key"] = credential.token
    return TelegramNotifierClient(resolved_source, origin=origin, **kwargs)


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "auth":
            if args.action == "login":
                result = login_interactive(origin=MANAGED_ORIGIN)
            elif args.action == "logout":
                result = logout()
            else:
                result = auth_status()
        else:
            client = _client(args.origin, args.source)
            if args.command == "inbox":
                result = client.inbox(after=args.after, limit=args.limit)
            elif args.command == "notify":
                result = client.notify(args.text, title=args.title, idempotency_key=args.idempotency_key)
            elif args.command == "notify-file":
                result = client.notify_file(args.file.read_bytes(), filename=args.file.name, content_type=args.content_type, photo=args.photo, caption=args.caption, idempotency_key=args.idempotency_key)
            elif args.command == "reply":
                result = client.reply(args.event_id, args.text, title=args.title, idempotency_key=args.idempotency_key)
            elif args.command == "reply-file":
                result = client.reply_file(args.event_id, args.file.read_bytes(), filename=args.file.name, content_type=args.content_type, photo=args.photo, caption=args.caption, idempotency_key=args.idempotency_key)
            elif args.command == "download":
                downloaded = client.download(args.event_id)
                with args.output.open("xb") as handle:
                    handle.write(downloaded["content"])
                result = {"saved": str(args.output), "sizeBytes": len(downloaded["content"]), "contentType": downloaded["content_type"], "filename": downloaded["filename"]}
            else:
                raise AssertionError("unhandled command")
        print(json.dumps(result, sort_keys=True))
        return 0
    except TelegramNotifierAuthRequired as exc:
        print(f"{exc} Sign in with 'telegram-notifier auth login' or set TELEGRAM_NOTIFIER_API_KEY; account: {exc.account_url}", file=sys.stderr)
        return 2
    except (TelegramNotifierError, PermissionError, OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
