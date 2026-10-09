# Changelog

## 0.2.1

- Public Ruby SDK source and documentation are available in AgentForge-Labs/telegram-notifier-distributions.
- RubyGems homepage, source, documentation and issue links now resolve anonymously without exposing the commercial backend.
- No runtime API or authentication changes.

## 0.2.0

- Migrated the Ruby package identity to `agentforge-telegram-notifier`.
- Migrated the namespace to `AgentForge::TelegramNotifier`.
- Switched from the legacy hosted-client contract to Telegram Notifier public v1
  (`/v1/inbox`, `/v1/file`, `/v1/notify`, `/v1/reply`).
- Added source-scoped `X-Notifier-Source` auth with optional Bearer credentials.
- Preserved idempotent retries, structured failures and credential redaction.
- Removed the legacy hosted OpenAPI snapshot/generated-operation dependency.
