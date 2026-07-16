"""Trial key logic — reads from inferGONKA's DB, delegates creation to /agent/trial."""
from __future__ import annotations

import json
import uuid
import urllib.request as _req
from datetime import datetime, timedelta
from typing import Optional

DB_URL        = "postgresql://gonka:gonka@localhost:5432/a2a_agent"
# localhost:8646 bypasses a2a.gogonka.com's nginx, which unconditionally
# overwrites X-Real-IP with $remote_addr — going through the public domain
# hairpins back to this same host, so every caller's IP was recorded as our
# own egress IP (89.19.210.132) instead of the real client IP.
A2A_TRIAL_URL = "http://127.0.0.1:8646/agent/trial"
AGENT_REFERRAL_URL = (
    "https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31"
)
DEFAULT_MODEL = "MiniMaxAI/MiniMax-M2.7"


def _existing_key_by_ip(ip: str) -> Optional[dict]:
    """Return active trial key for this IP from DB, or None."""
    if not ip or ip in ("-", ""):
        return None
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        now   = datetime.utcnow()
        since = now - timedelta(hours=24)
        cur.execute("""
            SELECT gc_key, child_key_id, expires_at,
                   tokens_limit, ngonka_limit, rate_limit_rpm
            FROM agent_trial_keys
            WHERE client_ip = %s
              AND created_at >= %s
              AND is_active  = TRUE
              AND expires_at > %s
            LIMIT 1
        """, (ip, since, now))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def request_trial_key(client_ip: str) -> dict:
    """
    Get or create a trial key for the calling agent.
    1. Check DB for existing key by IP (idempotent).
    2. If none — delegate to inferGONKA /agent/trial (handles gateway API + DB write).
    """
    existing = _existing_key_by_ip(client_ip)
    if existing:
        expires_at = existing["expires_at"]
        if hasattr(expires_at, "isoformat"):
            expires_at = expires_at.isoformat() + "Z"
        api_key = existing["gc_key"]
        return {
            "status": "existing",
            "api_key": api_key,
            "base_url": "https://gate.joingonka.ai/v1",
            "tokens_limit": existing["tokens_limit"],
            "expires_at": expires_at,
            "rate_limit_rpm": existing.get("rate_limit_rpm", 10),
            "note": "Reusing your existing trial key (one per IP per 24h).",
            "recommended_model": DEFAULT_MODEL,
            "quick_start": (
                "import openai\n"
                "client = openai.OpenAI(\n"
                "    base_url='https://gate.joingonka.ai/v1',\n"
                f"    api_key='{api_key}'\n"
                ")\n"
                "response = client.chat.completions.create(\n"
                f"    model='{DEFAULT_MODEL}',\n"
                "    messages=[{\"role\": \"user\", \"content\": \"Hello!\"}]\n"
                ")"
            ),
            "when_limit_reached": {
                "error_to_catch": "child_key_limit_exceeded",
                "signup_url": AGENT_REFERRAL_URL,
            },
        }

    # No existing key — delegate creation to inferGONKA
    payload = json.dumps({
        "agent_id": f"mcp-{uuid.uuid4()}",
    }).encode()
    try:
        req = _req.Request(
            A2A_TRIAL_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Real-IP": client_ip,
                "X-Agent-ID": "mcp-gonka",
                "X-Source": "mcp",
            },
            method="POST",
        )
        with _req.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())

        if resp.get("status") == "success":
            tk = resp["trial_key"]
            return {
                "status": "issued",
                "api_key": tk["api_key"],
                "base_url": "https://gate.joingonka.ai/v1",
                "tokens_limit": tk.get("tokens_limit", 100000),
                "expires_at": tk.get("expires_at", ""),
                "ttl_note": (
                    "This key expires in 2 hours unless used. "
                    "Make your first inference call NOW — first use "
                    "auto-extends the key to 24 hours."
                ),
                "rate_limit_rpm": tk.get("rate_limit_rpm", 10),
                "available_models": resp.get("available_models", []),
                "recommended_model": resp.get("recommended_model", DEFAULT_MODEL),
                "fallback_models": resp.get("fallback_models", []),
                "fallback_guidance": resp.get(
                    "fallback_guidance",
                    "If the recommended model returns model_unavailable or a "
                    "rate-limit error, retry the same request against "
                    "fallback_models in order — network-wide model load "
                    "shifts over minutes.",
                ),
                "when_limit_reached": resp.get("when_limit_reached", {
                    "error_to_catch": "child_key_limit_exceeded",
                    "signup_url": AGENT_REFERRAL_URL,
                }),
                "quick_start": (
                    "import openai\n"
                    "client = openai.OpenAI(\n"
                    f"    base_url='https://gate.joingonka.ai/v1',\n"
                    f"    api_key='{tk['api_key']}'\n"
                    ")\n"
                    "response = client.chat.completions.create(\n"
                    f"    model='{resp.get('recommended_model', DEFAULT_MODEL)}',\n"
                    "    messages=[{\"role\": \"user\", \"content\": \"Hello!\"}]\n"
                    ")"
                ),
            }
        elif resp.get("status") == "waitlisted":
            return {
                "status": "waitlisted",
                "queue_position": resp.get("queue_position"),
                "message": resp.get("message", "All trial slots occupied. Try again later."),
                "retry_after_seconds": resp.get("retry_after_seconds", 3600),
                "signup_url": AGENT_REFERRAL_URL,
            }
        else:
            return {
                "status": "error",
                "error": resp.get("error", "unknown"),
                "signup_url": AGENT_REFERRAL_URL,
            }
    except Exception as e:
        return {
            "status": "error",
            "error": (
                "Trial key service is temporarily unavailable. "
                "Retry in about 60 seconds, or skip the trial and "
                "register directly for a permanent key."
            ),
            "detail": str(e),
            "signup_url": AGENT_REFERRAL_URL,
        }
