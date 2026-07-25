"""Personal connector URLs — bind a user's own Gonka key to an opaque token.

Why this exists
---------------
Some MCP clients (notably claude.ai Connectors) only let you enter a URL — there's
no field to paste an API key / Authorization header. So "bring your own key" has
nowhere to go there. A personal URL solves it: the user mints a token bound to
their key, then connects to

    https://mcp.gogonka.com/k/<token>/mcp

nginx rewrites that to /mcp and forwards the token as the X-Personal-Token header;
_get_user_key() resolves token -> key, and the request runs under the user's key.

Security note: this store holds users' plaintext keys (we must forward them). The
file is 0600, owned by the service user. Tokens are opaque and revocable.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone

_STORE = "/opt/agentgonka/mcp-personal-keys.json"
_LOCK = threading.Lock()
_KEY_PREFIXES = ("jg-", "gc-", "sk-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    try:
        with open(_STORE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        d = os.path.dirname(_STORE)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".pk-", suffix=".tmp")
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _STORE)
        try:
            os.chmod(_STORE, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def looks_like_key(key: str) -> bool:
    return bool(key) and key.strip().lower().startswith(_KEY_PREFIXES)


def mint(jg_key: str) -> str | None:
    """Return a token bound to this key. Idempotent: the same key reuses its token."""
    key = (jg_key or "").strip()
    if not looks_like_key(key):
        return None
    with _LOCK:
        data = _load()
        for tok, rec in data.items():
            if rec.get("key") == key:
                return tok  # already minted
        tok = secrets.token_urlsafe(24)
        data[tok] = {"key": key, "created": _now(), "last_used": None}
        _save(data)
        return tok


def resolve(token: str) -> str | None:
    """Return the key bound to this token (and stamp last_used), or None."""
    token = (token or "").strip()
    if not token:
        return None
    with _LOCK:
        data = _load()
        rec = data.get(token)
        if not rec:
            return None
        rec["last_used"] = _now()
        data[token] = rec
        _save(data)
        return rec.get("key")


def revoke(token: str) -> bool:
    with _LOCK:
        data = _load()
        if token in data:
            del data[token]
            _save(data)
            return True
        return False
