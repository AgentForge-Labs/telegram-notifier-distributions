# frozen_string_literal: true

Gem::Specification.new do |spec|
  spec.name = "agentforge-telegram-notifier"
  spec.version = "0.2.1"
  spec.authors = ["AgentForge Labs"]
  spec.email = ["support@web-tasarimci.com"]
  spec.summary = "Official Ruby client for Telegram Notifier"
  spec.description = "A credential-safe Ruby client for the Telegram Notifier public v1 API. " \
                     "Supports source-scoped inbox, notification, reply and file flows with " \
                     "optional Bearer auth, idempotent writes, retries and structured errors."
  spec.homepage = "https://github.com/AgentForge-Labs/telegram-notifier-distributions"
  spec.license = "AGPL-3.0-only"
  spec.required_ruby_version = ">= 3.0"

  spec.metadata = {
    "homepage_uri" => "https://github.com/AgentForge-Labs/telegram-notifier-distributions",
    "source_code_uri" => "https://github.com/AgentForge-Labs/telegram-notifier-distributions",
    "bug_tracker_uri" => "https://github.com/AgentForge-Labs/telegram-notifier-distributions/issues",
    "documentation_uri" => "https://github.com/AgentForge-Labs/telegram-notifier-distributions/blob/main/sdk/ruby/README.md"
  }

  spec.files = Dir[
    "lib/**/*.rb",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "RUBYGEMS-PUBLISHING.md"
  ]
  spec.require_paths = ["lib"]
end
