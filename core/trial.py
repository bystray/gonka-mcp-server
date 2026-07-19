"""Trial key logic — reads from inferGONKA's DB, delegates creation to /agent/trial."""
from __future__ import annotations

import json
import uuid
import urllib.request as _req
from datetime import datetime, timedelta
from typing import Optional

from core.pricing import load_pricing, live_gateway_model_ids

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

BASE_URL_OPENAI    = "https://gate.joingonka.ai/v1"
BASE_URL_ANTHROPIC = "https://gate.joingonka.ai"

FALLBACK_GUIDANCE = (
    "If the recommended model returns model_unavailable or a "
    "rate-limit error, retry the same request against "
    "fallback_models in order — network-wide model load "
    "shifts over minutes."
)


def _when_limit_reached() -> dict:
    """Standard hint returned once a trial key's tokens run out.

    Always states the welcome-bonus size next to the signup link — a bare
    URL with no number gives the agent nothing to actually tell the user.
    """
    try:
        wb = load_pricing().get("welcome_bonus", {})
    except Exception:
        wb = {}
    ngnk = wb.get("amount_ngnk", 12_000_000)
    ngnk_fmt = f"{ngnk // 1_000_000}M" if ngnk % 1_000_000 == 0 else f"{ngnk:,}"
    return {
        "error_to_catch": "child_key_limit_exceeded",
        "signup_url": AGENT_REFERRAL_URL,
        "bonus": f"{ngnk_fmt} nGNK (~{wb.get('approx_tokens', 11_000):,} tokens) free on signup, no credit card.",
    }


def _build_setup(api_key: str, model: str) -> dict:
    """Copy-paste setup block returned with every trial key.

    Kept in one place so the `issued` and `existing` branches return an
    identical, self-contained instruction: which package to install, which
    params to set (base_url, api_key, model), for both OpenAI and Anthropic
    SDKs, plus a curl one-liner to verify the key before installing anything.
    """
    setup = {
        "base_url": BASE_URL_OPENAI,
        "base_url_anthropic": BASE_URL_ANTHROPIC,
        "quick_start_openai": (
            "pip install openai\n"
            "\n"
            "import openai\n"
            "client = openai.OpenAI(\n"
            f"    base_url='{BASE_URL_OPENAI}',\n"
            f"    api_key='{api_key}'\n"
            ")\n"
            "response = client.chat.completions.create(\n"
            f"    model='{model}',\n"
            "    messages=[{\"role\": \"user\", \"content\": \"Hello!\"}]\n"
            ")"
        ),
        "quick_start_anthropic": (
            "pip install anthropic\n"
            "\n"
            "import anthropic\n"
            "client = anthropic.Anthropic(\n"
            f"    base_url='{BASE_URL_ANTHROPIC}',\n"
            f"    api_key='{api_key}'\n"
            ")\n"
            "response = client.messages.create(\n"
            f"    model='{model}',\n"
            "    max_tokens=1024,\n"
            "    messages=[{\"role\": \"user\", \"content\": \"Hello!\"}]\n"
            ")"
        ),
        "quick_start_env": (
            f"OPENAI_BASE_URL={BASE_URL_OPENAI}\n"
            f"OPENAI_API_KEY={api_key}"
        ),
        "quick_start_curl": (
            f"curl {BASE_URL_OPENAI}/chat/completions \\\n"
            f"  -H 'Authorization: Bearer {api_key}' \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\"model\":\"{model}\",\"messages\":"
            "[{\"role\":\"user\",\"content\":\"Hello!\"}]}'"
        ),
        "one_command_setup": {
            "command": (
                f"JOINGONKA_API_KEY={api_key} npx @joingonka/setup "
                "--tool claude-code --non-interactive"
            ),
            "note": (
                "Optional third-party installer (github.com/unameisfine/"
                "joingonka-setup) that writes ANTHROPIC_BASE_URL/"
                "ANTHROPIC_AUTH_TOKEN (or the OpenAI-compatible equivalent) "
                "into the CALLING agent's OWN config — e.g. Claude Code's "
                "settings.json — redirecting its default model provider to "
                "Gonka. It backs up the config file first, but this still "
                "changes the user's own tool settings: ask the user before "
                "running it, don't run it automatically. --tool also "
                "accepts openclaw, cline, opencode, aider, kilo, roo, continue."
            ),
        },
    }
    # Back-compat: `quick_start` was the only snippet before this block existed.
    setup["quick_start"] = setup["quick_start_openai"]
    return setup


def _model_catalog(recommended: str) -> tuple[list, list]:
    """Return (available_models, fallback_models) from live pricing data.

    Mirrors get_available_models (server.py): filter by the gateway's live
    model ids when known; when the gateway is unreachable (live is None) keep
    the static status rather than marking everything unavailable.
    """
    try:
        data = load_pricing()
        live = live_gateway_model_ids()
    except Exception:
        return [], []
    available = []
    for m in data.get("models", []):
        mid = m.get("id")
        if not mid:
            continue
        status = (
            m.get("status") if live is None
            else ("available" if mid.lower() in live else "unavailable")
        )
        available.append({
            "id": mid,
            "status": status,
            "usd_per_1m_tokens": m.get("usd_per_1m_tokens_at_current"),
        })
    fallback = [
        m["id"] for m in available
        if m["id"] != recommended and m["status"] == "available"
    ]
    return available, fallback


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
        available_models, fallback_models = _model_catalog(DEFAULT_MODEL)
        result = {
            "status": "existing",
            "api_key": api_key,
            "tokens_limit": existing["tokens_limit"],
            "expires_at": expires_at,
            "rate_limit_rpm": existing.get("rate_limit_rpm", 10),
            "note": "Reusing your existing trial key (one per IP per 24h).",
            "recommended_model": DEFAULT_MODEL,
            "available_models": available_models,
            "fallback_models": fallback_models,
            "fallback_guidance": FALLBACK_GUIDANCE,
            "when_limit_reached": _when_limit_reached(),
        }
        result.update(_build_setup(api_key, DEFAULT_MODEL))
        return result

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
            recommended_model = resp.get("recommended_model", DEFAULT_MODEL)
            result = {
                "status": "issued",
                "api_key": tk["api_key"],
                "tokens_limit": tk.get("tokens_limit", 100000),
                "expires_at": tk.get("expires_at", ""),
                "ttl_note": (
                    "This key expires in 2 hours unless used. "
                    "Make your first inference call NOW — first use "
                    "auto-extends the key to 24 hours."
                ),
                "rate_limit_rpm": tk.get("rate_limit_rpm", 10),
                "available_models": resp.get("available_models", []),
                "recommended_model": recommended_model,
                "fallback_models": resp.get("fallback_models", []),
                "fallback_guidance": resp.get("fallback_guidance", FALLBACK_GUIDANCE),
                # Merge, don't just prefer one side: upstream owns error_to_catch/
                # signup_url if it sends its own, but "bonus" isn't something
                # upstream has ever included — guarantee it's there regardless.
                "when_limit_reached": {**_when_limit_reached(), **(resp.get("when_limit_reached") or {})},
            }
            result.update(_build_setup(tk["api_key"], recommended_model))
            return result
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
