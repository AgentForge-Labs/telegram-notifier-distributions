# agentforge-telegram-notifier for Ruby

Official Ruby client for the **Telegram Notifier public v1 API**. The source lives in
this monorepo under `sdk/ruby`; no separate Ruby repository is required.

## Install

After the RubyGems release is activated:

```bash
gem install agentforge-telegram-notifier
```

Bundler:

```ruby
gem "agentforge-telegram-notifier", "~> 0.2"
```

The gem requires Ruby >= 3.0 and has no runtime dependencies beyond the Ruby
standard library.

## Quick start

```ruby
require "agentforge-telegram-notifier"

client = AgentForge::TelegramNotifier::Client.new(
  source: "agent-a",
  key: ENV["TELEGRAM_NOTIFIER_KEY"]
)

event_page = client.inbox(limit: 20)
delivery = client.notify("Build finished", title: "CI")
puts delivery["delivery_id"]
```

The default origin is `http://127.0.0.1:8818`, matching the self-hosted Telegram
Notifier gateway. HTTPS origins can be supplied explicitly for an approved remote
Telegram Notifier deployment:

```ruby
client = AgentForge::TelegramNotifier::Client.new(
  source: "agent-a",
  key: ENV["TELEGRAM_NOTIFIER_KEY"],
  origin: "https://notify.example.com"
)
```

Plain HTTP is accepted only for loopback origins. Credentials are optional because a
self-hosted deployment may use source-only authorization. When supplied, the key is
sent as `Authorization: Bearer ...`. The client always owns the
`X-Notifier-Source` header.

## API helpers

- `inbox(after:, limit:)` → `GET /v1/inbox`
- `notify(text, title:, idempotency_key:)` → `POST /v1/notify`
- `notify_file(bytes, filename:, ...)` → `POST /v1/notify`
- `reply(event_id, text, ...)` → `POST /v1/reply`
- `reply_file(event_id, bytes, filename:, ...)` → `POST /v1/reply`
- `download(event_id)` → `GET /v1/file`
- `request(method, path, ...)` → guarded forward-compatible public `/v1/*` access

Every write gets an idempotency key. Safe retries reuse that exact key, so a transient
failure does not create a second logical delivery. The client rejects traversal,
absolute URLs and reserved private API paths.

Structured failures use:

- `AgentForge::TelegramNotifier::AuthError`
- `AgentForge::TelegramNotifier::QuotaError`
- `AgentForge::TelegramNotifier::DeliveryError`
- `AgentForge::TelegramNotifier::ValidationError`
- `AgentForge::TelegramNotifier::TransportError`

Credentials are redacted from `inspect`, error messages and stored error bodies.

## Development

```bash
cd sdk/ruby
gem build agentforge-telegram-notifier.gemspec
ruby -Ilib -Itest test/test_client.rb

# in another shell, start the fixture and pass its printed port
python ../ruby-conformance/fixture_server.py
ruby -Ilib ../ruby-conformance/conformance.rb http://127.0.0.1:PORT
```

The package is intentionally thin. It contains only the Ruby client, docs and license;
backend/web source and unrelated SDKs are excluded.

## License

GNU Affero General Public License v3.0 only.
