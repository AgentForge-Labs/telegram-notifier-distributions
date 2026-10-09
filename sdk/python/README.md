# AgentForge Telegram Notifier — Python

The canonical Python SDK and CLI live in the same monorepo under sdk/python.
No separate repository is required.

## Install

Install from PyPI with:

    python -m pip install agentforge-telegram-notifier

## Self-hosted / local gateway

Python example:

    from agentforge_telegram_notifier import TelegramNotifierClient

    client = TelegramNotifierClient(
        "my-agent",
        key="optional-api-key",
        origin="http://127.0.0.1:8818",
    )
    client.notify("Build finished")
    events = client.inbox(limit=50)

The client targets the public Telegram Notifier v1 routes /v1/inbox,
/v1/file, /v1/notify and /v1/reply. Every request carries
X-Notifier-Source; Bearer authentication is optional for trusted local
deployments and supported for authenticated deployments.

## Hosted OAuth / headless authentication

Browser login remains available for the managed service:

    telegram-notifier auth login
    telegram-notifier auth status
    telegram-notifier auth logout

For headless environments set TELEGRAM_NOTIFIER_API_KEY, or point
TELEGRAM_NOTIFIER_API_KEY_FILE at a 0600 secret file.

Set TELEGRAM_NOTIFIER_ORIGIN=https://relay.web-tasarimci.com for the managed
service and TELEGRAM_NOTIFIER_SOURCE when a source is not supplied by OAuth.

## CLI

    telegram-notifier --source my-agent inbox
    telegram-notifier --source my-agent notify "Deployment complete"
    telegram-notifier --source my-agent reply EVENT_ID "Acknowledged"
    telegram-notifier --source my-agent notify-file report.pdf
    telegram-notifier --source my-agent download EVENT_ID ./download.bin

Writes generate one idempotency key and reuse it across safe retries.
Credentials are redacted from structured errors and client repr output.

## Release boundary

The wheel and sdist contain only the Python client package, README and license.
They do not include gateway backend, web application, deployment files or
other language SDKs. Releases use this monorepo and fail closed when PyPI
ownership or publishing prerequisites are unavailable.
