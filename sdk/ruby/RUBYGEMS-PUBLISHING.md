# RubyGems publishing

Canonical RubyGems gem: agentforge-telegram-notifier.

The reviewed sdk/ruby source originates in the private AgentForge-Labs/telegram-notifier-public_commercial monorepo and is exported only after an explicit allowlist review to the public distribution repository:
https://github.com/AgentForge-Labs/telegram-notifier-distributions/tree/main/sdk/ruby

## Release process

The rubygems-release.yml workflow accepts exact X.Y.Z or telegram-notifier-ruby-vX.Y.Z tags. Both gemspec and internal Ruby VERSION must match.

1. Verify the canonical version and public/private artifact boundary.
2. Run Ruby unit tests and public v1 API conformance.
3. Build the gem with isolated pinned Ruby 3.3.12 on the Netcup long runner.
4. Authenticate through the permanent RubyGems Trusted Publisher OIDC binding for the private upstream, rubygems-release.yml and environment rubygems.
5. Publish to RubyGems and verify a fresh public registry install (PUBLIC_RUBYGEMS_INSTALL=PASS).

The official RubyGems configure-rubygems-credentials action is pinned to immutable v2.1.0 commit dc5a8d8553e6ee01fc26761a49e99e733d17954a. Interactive account credentials remain in the encrypted MCP publisher vault, not the code or CI. If publication or public registry install cannot be verified, release fails closed. The CI runner never receives production Docker daemon permissions.

Export public source before publishing and keep a source tag for each immutable gem release. Do not expose the hosted backend or private monorepo.
