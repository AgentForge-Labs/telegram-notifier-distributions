"""Thin Telegram Notifier v1 client with safe retries and credential redaction."""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote, urlparse
from urllib.request import Request, urlopen

DEFAULT_ORIGIN = "http://127.0.0.1:8818"
VERSION = "0.2.0"
RETRYABLE = {429, 502, 503, 504}
_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}$")


@dataclass(frozen=True)
class TelegramNotifierError(Exception):
    status: int
    code: str
    message: str
    request_id: str | None = None
    retry_after_seconds: int | None = None
    body: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"Telegram Notifier {self.code} ({self.status}): {self.message}"


class AuthError(TelegramNotifierError):
    pass


class QuotaError(TelegramNotifierError):
    pass


class DeliveryError(TelegramNotifierError):
    pass


class ValidationError(TelegramNotifierError):
    pass


class TransportError(TelegramNotifierError):
    pass


class TelegramNotifierClient:
    """Client for the public Telegram Notifier v1 REST surface."""

    def __init__(
        self,
        source: str,
        *,
        key: str | None = None,
        bearer_token: str | None = None,
        origin: str = DEFAULT_ORIGIN,
        timeout: float = 15.0,
        retries: int = 1,
        package_version: str = VERSION,
    ) -> None:
        source = source.strip()
        if not _SOURCE_RE.fullmatch(source):
            raise ValueError("source must be a valid non-empty Telegram Notifier source")
        if key is not None and bearer_token is not None:
            raise ValueError("provide only one credential")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 0:
            raise ValueError("retries must be non-negative")
        self.source = source
        self.origin = self._normalize_origin(origin)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self._credential = (key if key is not None else bearer_token or "").strip()
        self.user_agent = f"agentforge-telegram-notifier-python/{package_version}"

    def __repr__(self) -> str:
        credential = "[REDACTED]" if self._credential else "(none)"
        return (
            f"TelegramNotifierClient(source={self.source!r}, credential={credential}, "
            f"origin={self.origin!r}, retries={self.retries})"
        )

    @staticmethod
    def _normalize_origin(origin: str) -> str:
        value = origin.strip().rstrip("/")
        parsed = urlparse(value)
        if (
            not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("origin must be an http(s) origin without credentials, path, query or fragment")
        if parsed.scheme == "https":
            return value
        loopback = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not loopback:
            raise ValueError("plain HTTP is allowed only for loopback origins")
        return value

    @staticmethod
    def _safe_path(path: str) -> str:
        parsed = urlparse(path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or not path.startswith("/v1/")
        ):
            raise ValueError("only relative public /v1/* paths are allowed")
        lower = path.lower()
        if any(token in lower for token in ("%2f", "%5c", "%2e", "%25")):
            raise ValueError("encoded traversal or separators are forbidden")
        decoded = unquote(path)
        if "\\" in decoded or "//" in decoded:
            raise ValueError("invalid path")
        parts = decoded.removeprefix("/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("path traversal is forbidden")
        lower = decoded.lower()
        for prefix in ("/v1/admin", "/v1/internal", "/v1/saas-admin"):
            if lower == prefix or lower.startswith(prefix + "/"):
                raise ValueError("private API paths are not available through the client")
        return decoded

    @staticmethod
    def _idempotency_key(value: str | None) -> str:
        key = (value or "").strip() or uuid.uuid4().hex
        if len(key) < 8 or len(key) > 200 or "\r" in key or "\n" in key:
            raise ValueError("idempotency key must be 8-200 safe characters")
        return key

    @staticmethod
    def _event_id(value: str) -> str:
        value = str(value).strip()
        if not value or "/" in value or "\\" in value:
            raise ValueError("event id must be a non-empty path-safe value")
        return value

    @staticmethod
    def _filename(value: str) -> str:
        value = str(value).strip()
        if not value or "/" in value or "\\" in value or "\r" in value or "\n" in value:
            raise ValueError("filename must be a non-empty basename")
        return value

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self._credential, "[REDACTED]") if self._credential else value
        if isinstance(value, dict):
            return {str(k): self._redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact(v) for v in value]
        return value

    def _error(self, status: int, raw: bytes) -> TelegramNotifierError:
        try:
            parsed = json.loads(raw[:65536] or b"{}")
            body = parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            body = {}
        body = self._redact(body)
        nested = body.get("error")
        code = str(body.get("code") or "")
        message = str(body.get("message") or "")
        request_id = body.get("requestId")
        retry_after = body.get("retryAfterSeconds")

        if isinstance(nested, dict):
            code = code or str(nested.get("code") or "")
            message = message or str(nested.get("message") or nested.get("detail") or "")
            request_id = request_id or nested.get("requestId")
            retry_after = retry_after if retry_after is not None else nested.get("retryAfterSeconds")
        elif isinstance(nested, str):
            code = code or nested.upper().replace(" ", "_")
            message = message or nested

        code = self._redact(code or "REQUEST_FAILED")
        message = self._redact(message or code)
        retry_value = retry_after if isinstance(retry_after, int) and not isinstance(retry_after, bool) else None
        kwargs = dict(
            status=status,
            code=str(code),
            message=str(message),
            request_id=self._redact(request_id) if isinstance(request_id, str) else None,
            retry_after_seconds=retry_value,
            body=body,
        )
        if status in (401, 403):
            return AuthError(**kwargs)
        if status == 429 or str(code).upper() in {"QUOTA_EXCEEDED", "RATE_LIMITED"}:
            return QuotaError(**kwargs)
        if status in (502, 503, 504) or "DELIVERY" in str(code).upper():
            return DeliveryError(**kwargs)
        if status in (400, 404, 409, 422, 413):
            return ValidationError(**kwargs)
        return TelegramNotifierError(**kwargs)

    def _execute(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        path = self._safe_path(path)
        params = urlencode(query or {}, doseq=True)
        url = self.origin + path + (("?" + params) if params else "")
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "X-Notifier-Source": self.source,
            "User-Agent": self.user_agent,
        }
        if self._credential:
            headers["Authorization"] = f"Bearer {self._credential}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        attempts = self.retries + 1 if retry and (method == "GET" or idempotency_key) else 1
        last: TelegramNotifierError | None = None
        for attempt in range(attempts):
            request = Request(url, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(8 << 20)
                    if not raw:
                        return {}
                    try:
                        value = json.loads(raw)
                    except ValueError:
                        raise TransportError(response.status, "INVALID_RESPONSE", "invalid JSON response") from None
                    if not isinstance(value, dict):
                        raise TransportError(response.status, "INVALID_RESPONSE", "invalid JSON response")
                    return value
            except HTTPError as exc:
                last = self._error(exc.code, exc.read(65536))
                if attempt + 1 >= attempts or exc.code not in RETRYABLE or isinstance(last, QuotaError):
                    raise last from None
            except URLError:
                last = TransportError(0, "NETWORK_ERROR", "network request failed")
                if attempt + 1 >= attempts:
                    raise last from None
            time.sleep(min(0.05 * (2**attempt), 0.4))
        raise last or TransportError(0, "NETWORK_ERROR", "network request failed")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("unsupported HTTP method")
        key = None if method == "GET" else self._idempotency_key(idempotency_key)
        return self._execute(method, path, query=query, body=body, idempotency_key=key, retry=retry)

    def inbox(self, *, after: str | None = None, limit: int = 50) -> dict[str, Any]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("limit must be between 1 and 500")
        query: dict[str, Any] = {"limit": int(limit)}
        if after:
            query["after"] = after
        return self._execute("GET", "/v1/inbox", query=query)

    def notify(
        self,
        text: str,
        *,
        title: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = self._idempotency_key(idempotency_key)
        return self._execute(
            "POST",
            "/v1/notify",
            body={"kind": "text", "title": title, "text": text},
            idempotency_key=key,
        )

    def notify_file(
        self,
        content: bytes,
        *,
        filename: str,
        content_type: str = "application/octet-stream",
        photo: bool = False,
        caption: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = self._idempotency_key(idempotency_key)
        return self._execute(
            "POST",
            "/v1/notify",
            body={
                "kind": "photo" if photo else "document",
                "filename": self._filename(filename),
                "content_type": content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "text": caption,
            },
            idempotency_key=key,
        )

    def reply(
        self,
        event_id: str,
        text: str,
        *,
        title: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = self._idempotency_key(idempotency_key)
        return self._execute(
            "POST",
            "/v1/reply",
            body={"event_id": self._event_id(event_id), "kind": "text", "title": title, "text": text},
            idempotency_key=key,
        )

    def reply_file(
        self,
        event_id: str,
        content: bytes,
        *,
        filename: str,
        content_type: str = "application/octet-stream",
        photo: bool = False,
        caption: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        key = self._idempotency_key(idempotency_key)
        return self._execute(
            "POST",
            "/v1/reply",
            body={
                "event_id": self._event_id(event_id),
                "kind": "photo" if photo else "document",
                "filename": self._filename(filename),
                "content_type": content_type,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "text": caption,
            },
            idempotency_key=key,
        )

    def download(self, event_id: str) -> dict[str, Any]:
        result = self._execute("GET", "/v1/file", query={"event_id": self._event_id(event_id)})
        encoded = result.get("content_base64")
        if not isinstance(encoded, str):
            raise TransportError(0, "INVALID_FILE_PAYLOAD", "missing file payload")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError:
            raise TransportError(0, "INVALID_FILE_PAYLOAD", "invalid file payload") from None
        return {
            "filename": str(result.get("filename") or ""),
            "content_type": str(result.get("content_type") or "application/octet-stream"),
            "content": content,
        }
