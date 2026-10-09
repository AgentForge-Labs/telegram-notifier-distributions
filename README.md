# Telegram Notifier — Public SDK source and CLI distributions

This is the **public distribution repository** for the AgentForge Labs Telegram Notifier client SDKs and standalone CLI. The hosted Telegram relay backend, private infrastructure, and commercial monorepo are **not published** here.

## Ruby SDK (AGPL-3.0-only)

Install version 0.2.0 from RubyGems:

```sh
gem install agentforge-telegram-notifier -v 0.2.0
```

- [Public RubyGems package](https://rubygems.org/gems/agentforge-telegram-notifier)
- [Corresponding Ruby 0.2.0 source](sdk/ruby/)
- [Ruby usage and development guide](sdk/ruby/README.md)
- [AGPL-3.0 license](LICENSE)

The immutable 0.2.0 gemspec contains historical metadata pointing to the upstream private monorepo. This public tree preserves the **exact same source version** that was published. Future releases will point package metadata here.

## Standalone CLI

The reviewed, client-only [Go CLI source](cli/telegram-notifier/) is available here. Downloadable platform archives, SHA-256 checksums and release notes will appear on [GitHub Releases](https://github.com/AgentForge-Labs/telegram-notifier-distributions/releases) once built and verified. A public source tree alone is **not** a claim that CLI packages are available yet.

## Security and development

Only whitelisted SDK and CLI source files were copied from the private upstream. There are no production service implementations, runtime credentials, deployment manifests, token files or server environment configuration here. Please report bugs using this repository's Issues page. Verify package publisher identity and checksums before installing.
