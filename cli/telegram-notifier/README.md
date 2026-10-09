# Telegram Notifier standalone CLI

`telegram-notifier` is the runtime-free command line client distributed by issue #86. Its source lives in this monorepo; there is no separate CLI source repository.

The binary targets the Telegram Notifier public v1 API and defaults to `http://127.0.0.1:8818`. Remote origins must use HTTPS. Every request sends `X-Notifier-Source`; Bearer credentials are optional for deployments that require them.

## Authentication

Interactive OAuth uses Authorization Code + PKCE:

```bash
telegram-notifier --base-url https://notifier.example auth login
telegram-notifier auth status
telegram-notifier auth logout
```

Headless environments use either `TELEGRAM_NOTIFIER_TOKEN` or a private `TELEGRAM_NOTIFIER_TOKEN_FILE`. Credentials are never accepted as command-line arguments.

## Public v1 operations

```bash
telegram-notifier inbox --limit 20
telegram-notifier notify --text "deploy complete"
telegram-notifier reply --event-id evt_123 --text "ack"
telegram-notifier download --event-id evt_123 --output ./attachment.bin
```

Writes use one idempotency key across safe retries. An explicit key can be supplied with `--idempotency-key`.

Release archives and package-manager submission manifests are built from `cli/telegram-notifier/release.json`. External Homebrew/WinGet/Scoop/Chocolatey publication is not claimed until the corresponding registry ownership/credentials and public submission evidence exist.
