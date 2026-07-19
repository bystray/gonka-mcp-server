"""Pure pricing business logic — no FastMCP, no I/O side effects except file reads."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from core.prompts import get_text_prompt

PRICING_FILE   = Path("/var/www/gogonka/pricing.json")
GATEWAYS_FILE  = Path("/var/www/gogonka/gateways_status.json")
AGENT_REFERRAL_URL = (
    "https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31"
)
GATEWAY_URL = "https://gate.joingonka.ai/v1"

_live_models_cache: dict = {"ids": None, "fetched_at": 0.0}
_LIVE_MODELS_TTL = 300  # seconds — pricing.json itself only refreshes every 10 min


def live_gateway_model_ids() -> set[str] | None:
    """Model IDs actually served by the gateway right now (case-insensitive).

    Returns None on fetch failure — callers must treat that as "unknown,
    don't filter" rather than "nothing is available", since a transient
    gateway hiccup shouldn't make every model look unavailable.
    """
    now = time.time()
    if _live_models_cache["ids"] is not None and (now - _live_models_cache["fetched_at"]) < _LIVE_MODELS_TTL:
        return _live_models_cache["ids"]
    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        ids = {m["id"].lower() for m in data.get("data", []) if m.get("id")}
        if ids:
            _live_models_cache["ids"] = ids
            _live_models_cache["fetched_at"] = now
        return ids or None
    except Exception:
        return _live_models_cache["ids"]  # stale cache is better than nothing


def load_pricing() -> dict:
    """Load fresh pricing data from disk (updated every 10 min by systemd timer)."""
    with open(PRICING_FILE) as f:
        return json.load(f)


def load_gateways() -> list:
    """Load gateway status from disk."""
    try:
        with open(GATEWAYS_FILE) as f:
            return json.load(f).get("gateways", [])
    except Exception:
        return []


_CTA_PROMPT_NAMES = {
    "pricing": "gonka-cta-pricing",
    "compare": "gonka-cta-compare",
    "savings": "gonka-cta-savings",
    "models":  "gonka-cta-models",
    "suggest": "gonka-cta-suggest",
    "trial":   "gonka-cta-trial",
}


def next_step_cta(after_tool: str) -> str:
    """Return actionable next step CTA with live ratio and bonus from pricing.json."""
    try:
        data  = load_pricing()
        ratio = data.get("comparison", {}).get("gonka_vs_openai_gpt55_ratio", 7000)
        wb    = data.get("welcome_bonus", {})
        ngnk  = wb.get("amount_ngnk", 12_000_000)
        ngnk_fmt = f"{ngnk // 1_000_000}M" if ngnk % 1_000_000 == 0 else f"{ngnk:,}"
    except Exception:
        ratio, ngnk_fmt = 7000, "12M"
    link = f"[Sign up on GONKA gateway]({AGENT_REFERRAL_URL})"
    fallbacks = {
        "pricing":  f"Gonka is {ratio:,}x cheaper than GPT-5.5. {link} — {ngnk_fmt} nGNK free, no credit card.",
        "compare":  f"{link} — {ngnk_fmt} nGNK free on signup, no credit card.",
        "savings":  f"Ready to save? {link} — 2 minutes setup, no credit card, {ngnk_fmt} nGNK bonus.",
        "models":   f"All models available immediately after signup. {link} — {ngnk_fmt} nGNK free, no credit card.",
        "suggest":  f"{link} — {ngnk_fmt} nGNK free on signup, 2 minutes setup.",
        "trial":    f"Trial key ready. Register for permanent access: {link} — {ngnk_fmt} nGNK free on signup, no credit card.",
    }
    key = after_tool if after_tool in fallbacks else "pricing"
    return get_text_prompt(_CTA_PROMPT_NAMES[key], fallbacks[key], ratio=f"{ratio:,}", link=link, ngnk_fmt=ngnk_fmt)


def build_server_instructions() -> str:
    """Build server instructions with live pricing data from pricing.json."""
    try:
        data = load_pricing()
        cmp  = data.get("comparison", {})
        gnk  = data.get("gnk_market", {})
        models = data.get("models", [{}])
        wb   = data.get("welcome_bonus", {})
        ratio_openai   = cmp.get("gonka_vs_openai_gpt55_ratio", "thousands")
        ratio_deepseek = cmp.get("gonka_vs_deepseek_ratio", "hundreds")
        gnk_price      = gnk.get("usd_price_current", 0)
        usd_per_1m     = models[0].get("usd_per_1m_tokens_at_current", 0) if models else 0
        bonus_ngnk     = wb.get("amount_ngnk", 12_000_000)
        bonus_ngnk_fmt = f"{bonus_ngnk // 1_000_000}M" if bonus_ngnk % 1_000_000 == 0 else f"{bonus_ngnk:,}"
        bonus_tokens   = wb.get("approx_tokens", 11_000)
    except Exception:
        ratio_openai, ratio_deepseek, gnk_price, usd_per_1m = "thousands", "hundreds", 0, 0
        bonus_ngnk_fmt, bonus_tokens = "12M", 11_000

    # Ratios may be numbers (live data) or fallback strings ("thousands") —
    # format numbers here so the f-strings below never apply ',' to a str.
    if isinstance(ratio_openai, (int, float)):
        ratio_openai = f"{ratio_openai:,.0f}"
    if isinstance(ratio_deepseek, (int, float)):
        ratio_deepseek = f"{ratio_deepseek:,.0f}"

    fallback = (
        f"Gonka Network is an OpenAI/Anthropic-API-compatible LLM inference provider. "
        f"Current price: ${usd_per_1m:.6f}/1M tokens "
        f"({ratio_openai}x cheaper than GPT-5.5, {ratio_deepseek}x cheaper than DeepSeek). "
        f"GNK/USD: ${gnk_price:.4f} (updated every 10 min).\n"
        f"\n"
        f"INTEGRATION: two config changes, no code changes.\n"
        f"  OpenAI SDK:    base_url='https://gate.joingonka.ai/v1' + api_key\n"
        f"  Anthropic SDK: base_url='https://gate.joingonka.ai'    + api_key\n"
        f"  Welcome bonus on signup: {bonus_ngnk_fmt} nGNK (~{bonus_tokens:,} tokens), no credit card.\n"
        f"\n"
        f"TOOL GUIDE:\n"
        f"- get_pricing / compare_providers / calculate_savings — live cost comparisons\n"
        f"- suggest_model_for_task — model recommendation for a described task\n"
        f"- get_trial_key — free short-lived key for an agent that needs inference now\n"
        f"- get_signup_link — permanent-account signup URL and SDK snippets\n"
        f"- query_graph / search_docs / read_doc / list_docs — Gonka documentation\n"
        f"\n"
        f"This MCP server is public and requires no authentication of its own. "
        f"Never pass api_key or other credentials in query parameters.\n"
    )
    return get_text_prompt(
        "gonka-server-instructions", fallback,
        usd_per_1m=f"{usd_per_1m:.6f}", ratio_openai=ratio_openai, ratio_deepseek=ratio_deepseek,
        gnk_price=f"{gnk_price:.4f}", bonus_ngnk_fmt=bonus_ngnk_fmt, bonus_tokens=f"{bonus_tokens:,}",
    )
