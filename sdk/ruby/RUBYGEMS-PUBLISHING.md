# RubyGems publishing

Canonical gem: `agentforge-telegram-notifier`.

Source remains in the
`AgentForge-Labs/telegram-notifier-public_commercial` monorepo under `sdk/ruby`.
Do not create or sync a separate Ruby source repository.

## Release

The `rubygems-release` workflow accepts an explicit stable `X.Y.Z` version or the
`telegram-notifier-ruby-vX.Y.Z` tag.

Before publication it:

1. verifies the gem version,
2. runs Ruby unit tests and Telegram Notifier public-v1 conformance,
3. builds the exact gem,
4. verifies the thin distribution boundary,
5. installs the built gem in an isolated Ruby container.

Publication uses RubyGems GitHub OIDC Trusted Publishing via
`rubygems/configure-rubygems-credentials@v2` in the protected `rubygems` environment.
The account owner must configure the matching pending trusted publisher for
`AgentForge-Labs/telegram-notifier-public_commercial` and
`rubygems-release.yml`. The interactive account password stays in the
encrypted MCP publisher vault, not in this repository or its CI inputs.
If RubyGems cannot authorize the OIDC identity, publication fails closed.

After a push, the workflow installs the exact public version from RubyGems and requires
`PUBLIC_RUBYGEMS_INSTALL=PASS`.

At migration time the canonical gem page returned 404, so this repository does not
claim that public publication already happened. The former legacy gem identity is
retired from this workflow and must not receive new releases.
