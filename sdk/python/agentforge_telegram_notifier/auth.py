"""OAuth PKCE and API-key credential helpers for Telegram Notifier."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

MANAGED_ORIGIN = "https://relay.web-tasarimci.com"
# Protocol compatibility identifier registered by the hosted OAuth service.
CLIENT_ID = "agentrelay-cli"
DEFAULT_SCOPES = "relay:read relay:write offline_access"


class TelegramNotifierAuthRequired(RuntimeError):
    def __init__(self, message: str = "Telegram Notifier authentication is required.") -> None:
        super().__init__(message)
        self.account_url = MANAGED_ORIGIN + "/account"


@dataclass(frozen=True)
class ResolvedCredential:
    token: str
    source: str = ""
    kind: str = "oauth"
    origin: str = MANAGED_ORIGIN


def _config_dir() -> Path:
    override = os.getenv("TELEGRAM_NOTIFIER_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "AgentForge" / "TelegramNotifier"
    import sys
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AgentForge" / "TelegramNotifier"
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "agentforge" / "telegram-notifier"


def credential_path() -> Path:
    return _config_dir() / "credentials.json"


def _safe_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        os.chmod(path.parent, 0o700)
    temp = path.with_name("." + path.name + "." + secrets.token_hex(6) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _read_store(path: Path | None = None) -> dict[str, Any]:
    target = path or credential_path()
    try:
        if target.stat().st_size > 65536:
            return {}
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _protected_api_key_file(path: Path) -> str:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise PermissionError("Telegram Notifier API key path must be a regular file.")
    if os.name != "nt" and info.st_mode & 0o077:
        raise PermissionError("Telegram Notifier API key file must not be group/world accessible.")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("Telegram Notifier API key file is empty.")
    return value


def _post_form(url: str, values: dict[str, str], timeout: float = 15.0) -> dict[str, Any]:
    body = urllib.parse.urlencode(values).encode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(65536)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("Telegram Notifier OAuth returned an invalid response.")
    return value


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def refresh_credentials(store: dict[str, Any], *, origin: str = MANAGED_ORIGIN) -> dict[str, Any]:
    refresh = str(store.get("refreshToken") or "")
    if not refresh:
        raise TelegramNotifierAuthRequired("Telegram Notifier login has expired; sign in again.")
    result = _post_form(
        origin.rstrip("/") + "/oauth/token",
        {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLIENT_ID},
    )
    updated = {
        "version": 1,
        "origin": origin.rstrip("/"),
        "accessToken": str(result["access_token"]),
        "refreshToken": str(result.get("refresh_token") or ""),
        "expiresAt": int(time.time()) + int(result.get("expires_in") or 3600),
        "source": str(result.get("source") or store.get("source") or ""),
        "scope": str(result.get("scope") or store.get("scope") or ""),
    }
    _safe_write(credential_path(), updated)
    return updated


def resolve_credential(*, allow_stored: bool = True, required: bool = True) -> ResolvedCredential:
    env_key = os.getenv("TELEGRAM_NOTIFIER_API_KEY", "").strip()
    if env_key:
        return ResolvedCredential(env_key, kind="api_key_env")
    file_name = os.getenv("TELEGRAM_NOTIFIER_API_KEY_FILE", "").strip()
    if file_name:
        return ResolvedCredential(
            _protected_api_key_file(Path(file_name).expanduser()),
            kind="api_key_file",
        )
    if allow_stored:
        store = _read_store()
        access = str(store.get("accessToken") or "")
        if access and int(store.get("expiresAt") or 0) > int(time.time()) + 30:
            return ResolvedCredential(
                access,
                str(store.get("source") or ""),
                "oauth",
                str(store.get("origin") or MANAGED_ORIGIN),
            )
        if store.get("refreshToken"):
            origin = str(store.get("origin") or MANAGED_ORIGIN)
            updated = refresh_credentials(store, origin=origin)
            return ResolvedCredential(
                str(updated["accessToken"]),
                str(updated.get("source") or ""),
                "oauth",
                origin,
            )
    if required:
        raise TelegramNotifierAuthRequired()
    return ResolvedCredential("", kind="none", origin="")


def auth_status() -> dict[str, Any]:
    if os.getenv("TELEGRAM_NOTIFIER_API_KEY", "").strip():
        return {"authenticated": True, "kind": "api_key_env", "origin": MANAGED_ORIGIN}
    file_name = os.getenv("TELEGRAM_NOTIFIER_API_KEY_FILE", "").strip()
    if file_name:
        try:
            _protected_api_key_file(Path(file_name).expanduser())
            return {"authenticated": True, "kind": "api_key_file", "origin": MANAGED_ORIGIN}
        except (OSError, ValueError, PermissionError):
            return {"authenticated": False, "kind": "api_key_file", "origin": MANAGED_ORIGIN}
    store = _read_store()
    if not store:
        return {"authenticated": False, "kind": "none", "origin": MANAGED_ORIGIN}
    return {
        "authenticated": bool(store.get("accessToken") or store.get("refreshToken")),
        "kind": "oauth",
        "origin": str(store.get("origin") or MANAGED_ORIGIN),
        "expiresAt": int(store.get("expiresAt") or 0),
        "source": str(store.get("source") or ""),
        "refreshAvailable": bool(store.get("refreshToken")),
    }


def logout(*, origin: str | None = None) -> dict[str, Any]:
    path = credential_path()
    store = _read_store(path)
    target = (origin or str(store.get("origin") or MANAGED_ORIGIN)).rstrip("/")
    token = str(store.get("refreshToken") or store.get("accessToken") or "")
    if token:
        try:
            _post_form(target + "/oauth/revoke", {"token": token, "client_id": CLIENT_ID}, timeout=5.0)
        except Exception:
            pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return {"authenticated": False, "kind": "none", "origin": target}


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}
    expected_state = ""

    def log_message(self, *_args: Any) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        state = str((query.get("state") or [""])[-1])
        code = str((query.get("code") or [""])[-1])
        error = str((query.get("error") or [""])[-1])
        if parsed.path != "/callback" or not secrets.compare_digest(state, self.expected_state):
            self.send_response(400)
            body = b"Invalid Telegram Notifier OAuth callback."
        else:
            type(self).result = {"code": code, "error": error, "state": state}
            self.send_response(200)
            body = b"Telegram Notifier authorization complete. You may close this window."
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def login_interactive(
    *,
    origin: str = MANAGED_ORIGIN,
    timeout: float = 180.0,
    browser_open: Callable[[str], Any] = webbrowser.open,
) -> dict[str, Any]:
    origin = origin.rstrip("/")
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    handler = type("TelegramNotifierCallback", (_CallbackHandler,), {"result": {}, "expected_state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    redirect = f"http://127.0.0.1:{server.server_port}/callback"
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": DEFAULT_SCOPES,
            "state": state,
        }
    )
    url = origin + "/oauth/authorize?" + query
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if browser_open(url) is False:
            raise RuntimeError(
                "Could not open the browser; use TELEGRAM_NOTIFIER_API_KEY or "
                "TELEGRAM_NOTIFIER_API_KEY_FILE for headless use."
            )
        deadline = time.monotonic() + timeout
        while not handler.result and time.monotonic() < deadline:
            time.sleep(0.05)
        if not handler.result:
            raise TimeoutError("Timed out waiting for Telegram Notifier browser authorization.")
        if handler.result.get("error"):
            raise PermissionError("Telegram Notifier authorization was denied.")
        result = _post_form(
            origin + "/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": handler.result.get("code", ""),
                "redirect_uri": redirect,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        stored = {
            "version": 1,
            "origin": origin,
            "accessToken": str(result["access_token"]),
            "refreshToken": str(result.get("refresh_token") or ""),
            "expiresAt": int(time.time()) + int(result.get("expires_in") or 3600),
            "source": str(result.get("source") or ""),
            "scope": str(result.get("scope") or ""),
        }
        _safe_write(credential_path(), stored)
        return auth_status()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
