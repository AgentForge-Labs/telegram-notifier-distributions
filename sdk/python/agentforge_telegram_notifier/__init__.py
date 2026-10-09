"""Python SDK and CLI primitives for AgentForge Telegram Notifier."""

from .client import (
    DEFAULT_ORIGIN,
    VERSION,
    AuthError,
    DeliveryError,
    QuotaError,
    TelegramNotifierClient,
    TelegramNotifierError,
    TransportError,
    ValidationError,
)
from .auth import (
    MANAGED_ORIGIN,
    ResolvedCredential,
    TelegramNotifierAuthRequired,
    auth_status,
    login_interactive,
    logout,
    resolve_credential,
)

__all__ = [
    "DEFAULT_ORIGIN",
    "MANAGED_ORIGIN",
    "VERSION",
    "TelegramNotifierClient",
    "TelegramNotifierError",
    "AuthError",
    "QuotaError",
    "DeliveryError",
    "ValidationError",
    "TransportError",
    "TelegramNotifierAuthRequired",
    "ResolvedCredential",
    "auth_status",
    "login_interactive",
    "logout",
    "resolve_credential",
]
