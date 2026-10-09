# Telegram Notifier — Public SDK source and CLI distributions

This repository hosts reviewed public source for Telegram Notifier clients and verified public CLI releases. The hosted relay service, proprietary backend, infrastructure and credentials remain private.

## Ruby SDK (AGPL-3.0-only)

RubyGems: https://rubygems.org/gems/agentforge-telegram-notifier

Install the verified v0.2.0 package:

```sh
gem install agentforge-telegram-notifier -v 0.2.0
```

- **Immutable v0.2.0 source**: [Ruby SDK release source](https://github.com/AgentForge-Labs/telegram-notifier-distributions/tree/telegram-notifier-ruby-v0.2.0/sdk/ruby)
- **v0.2.1 source / corrected public links**: [current Ruby SDK](sdk/ruby/) (package publication is independently verified on RubyGems)
- [Ruby SDK README](sdk/ruby/README.md) and [AGPL license](LICENSE)

The historical 0.2.0 gemspec linked to a private monorepo. The v0.2.1 source corrects this; the immutable 0.2.0 release artifact is unchanged.

## Standalone Go CLI

[CLI source](cli/telegram-notifier/). Public binaries and checksums: [Telegram Notifier CLI v0.1.0](https://github.com/AgentForge-Labs/telegram-notifier-distributions/releases/tag/telegram-notifier-cli-v0.1.0).

Six release archives cover Linux, macOS and Windows on amd64 and arm64. Verify downloads using the included checksums.txt SHA-256 file and inspect provenance.json for build metadata; the metadata is not a signed attestation.

## Security

The public source was exported from a fixed allowlist of SDK/CLI paths. It contains no private backend implementation, production secrets, tokens or infrastructure configuration. Report public client issues via this repository's Issues page. Package-manager submission and registry approvals are verified separately.
