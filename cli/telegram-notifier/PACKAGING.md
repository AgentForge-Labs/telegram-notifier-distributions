# Standalone CLI package-manager submissions

Issue #86 keeps all CLI source in this monorepo. The release workflow cross-builds
`telegram-notifier` for Linux, macOS and Windows on amd64/arm64, publishes immutable
GitHub Release archives, checksums and provenance, then generates submission bundles
for:

- Homebrew formula: `telegram-notifier`
- WinGet package: `AgentForge.TelegramNotifier`
- Scoop manifest: `telegram-notifier`
- Chocolatey package: `agentforge-telegram-notifier`

The manifests point only to exact GitHub Release archives and SHA-256 values. They do
not install the Telegram gateway daemon or backend/web/deployment source.

Public package-manager publication requires registry-side ownership/approval that is
outside this source repository. Until public evidence exists, the project records these
surfaces as submission-ready rather than published. No separate source repository is
created for the CLI.
