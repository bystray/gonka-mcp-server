"""Inference proxy — runs LLM calls THROUGH this server.

Why this exists
---------------
An MCP server can only hand back data; it cannot flip the host agent's model
provider. `get_trial_key` returns a key, but a sandboxed agent often can't open
its own socket to the gateway (blocked egress) or rewrite its own config. This
tool closes that gap: the agent sends a prompt over the already-open MCP channel,
THIS server calls gate.joingonka.ai and returns the answer. The agent never needs
outbound network or a config change.

Two modes (auto-detected by the caller)
---------------------------------------
- TRIAL: no user key. The server issues a short-lived trial child key (one per IP,
  ~150000 nGNK/day) and proxies under it. Budget-limited, converts to signup on
  exhaustion, and is rate-limited per IP at this layer so the shared parent key
  can't be drained by load on one address.
- REGISTERED: the caller pasted their own Gonka key (jg-…) into their MCP client;
  it arrives as `Authorization: Bearer …`. We proxy under THAT key — their own
  balance, no trial cap, no signup nudge.

Budget lifecycle (trial only)
-----------------------------
Below 80%: answer + running budget. >= 80%: answer + a soft warning telling the
MAIN model to offer signup before the hard cutoff. Exhausted (gateway HTTP 402
child_key_limit_exceeded, or our local counter crosses the cap): no answer —
instead usage stats, the savings, the bonus link, and instructions for the MAIN
model. Local accounting is best-effort for the 80% nudge; the 402 is the
authoritative hard stop.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import concurrent.futures as _cf
import urllib.request as _req
import urllib.error as _err
from datetime import datetime, timezone

from core.pricing import load_pricing, AGENT_REFERRAL_URL, live_gateway_model_ids
from core.trial import (
    request_trial_key,
    _existing_key_by_ip,
    _when_limit_reached,
    DEFAULT_MODEL,
)

GATEWAY_CHAT_URL = "https://gate.joingonka.ai/v1/chat/completions"
FALLBACK_MODEL   = "moonshotai/Kimi-K2.6"
GLM_MODEL        = "zai-org/GLM-5.2-FP8"   # announced; not live yet — verify id when it is
# Canonical model ids in preference order. GLM auto-joins auto/second-opinion the
# moment the live gateway starts serving it — no code change needed.
KNOWN_MODELS = [DEFAULT_MODEL, FALLBACK_MODEL, GLM_MODEL]
MODEL_ALIASES = {
    "minimax": DEFAULT_MODEL, "m2.7": DEFAULT_MODEL, "minimax-m2.7": DEFAULT_MODEL,
    "kimi": FALLBACK_MODEL, "k2.6": FALLBACK_MODEL, "kimi-k2.6": FALLBACK_MODEL,
    "glm": GLM_MODEL, "glm-5.2": GLM_MODEL,
}

DEFAULT_LIMIT_NGONKA = 150000
WARN_THRESHOLD   = 0.80          # soft-warn the main model at 80% spent
MAX_PROMPT_CHARS = 24000         # guard against runaway prompts on a trial key
MAX_TOKENS_CAP   = 2048          # cap completion size (gonka_chat)
SECOND_OPINION_MAX_TOKENS = 1024   # hard cap per opinion; MiniMax is a reasoning model
SECOND_OPINION_DEFAULT_TOKENS = 768  # default — enough to finish thinking + a concise answer
MAX_OPINIONS = 5                 # hard cap on sub-calls per second-opinion (budget/latency)
MAX_PERSPECTIVE_LEN = 60         # each perspective label is a short role/stance
NGONKA_PER_TOKEN = 19.8          # measured on gate.joingonka.ai at current price

# Per-IP daily call cap on the trial proxy (defence-in-depth over the gateway's
# per-key nGNK cap: stops one address from draining the shared parent key/slots).
MAX_SUBCALLS_PER_IP_PER_DAY = 100
_RATELIMIT_FILE = "/opt/agentgonka/mcp-proxy-ratelimit.json"

# Local best-effort spend counter, keyed by child_key_id (falls back to gc_key).
# {key: {"spent_ngnk": float, "spent_usd": float, "calls": int, "limit_ngnk": int}}
_USAGE_FILE = "/opt/agentgonka/mcp-trial-usage.json"
_USAGE_LOCK = threading.Lock()
_RL_LOCK = threading.Lock()

SYNTHESIS_INSTRUCTIONS = (
    "These are independent answers to the same prompt from Gonka models — and, when a "
    "`perspective` is present, from that assigned role/stance. In your reply: compare "
    "them with your OWN view, attribute each opinion to its model and perspective "
    "(e.g. 'Gonka MiniMax, as a skeptic, says…'), and point out where they agree and "
    "differ. Do NOT present any model's answer as your own, and do NOT alter the text."
)


# --------------------------------------------------------------------------- #
# Local spend ledger (soft accounting for the 80% nudge; 402 is the hard stop) #
# --------------------------------------------------------------------------- #
def _load_ledger() -> dict:
    try:
        with open(_USAGE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ledger(data: dict) -> None:
    _atomic_write(_USAGE_FILE, data)


def _atomic_write(path: str, data: dict) -> None:
    try:
        d = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        pass


def _ledger_entry(key_id: str, limit_ngnk: int) -> dict:
    data = _load_ledger()
    e = data.get(key_id)
    if not e:
        e = {"spent_ngnk": 0.0, "spent_usd": 0.0, "calls": 0, "limit_ngnk": limit_ngnk}
    e["limit_ngnk"] = limit_ngnk or e.get("limit_ngnk") or DEFAULT_LIMIT_NGONKA
    return e


def _bump_ledger(key_id: str, ngnk: float, usd: float, limit_ngnk: int) -> dict:
    with _USAGE_LOCK:
        data = _load_ledger()
        e = data.get(key_id) or {"spent_ngnk": 0.0, "spent_usd": 0.0, "calls": 0}
        e["spent_ngnk"] = float(e.get("spent_ngnk", 0.0)) + float(ngnk or 0.0)
        e["spent_usd"]  = float(e.get("spent_usd", 0.0)) + float(usd or 0.0)
        e["calls"]      = int(e.get("calls", 0)) + 1
        e["limit_ngnk"] = limit_ngnk or e.get("limit_ngnk") or DEFAULT_LIMIT_NGONKA
        data[key_id] = e
        _save_ledger(data)
        return e


def _mark_exhausted(key_id: str, limit_ngnk: int) -> None:
    """Force the local counter to the cap so subsequent calls short-circuit."""
    with _USAGE_LOCK:
        data = _load_ledger()
        e = data.get(key_id) or {"spent_ngnk": 0.0, "spent_usd": 0.0, "calls": 0}
        e["limit_ngnk"] = limit_ngnk or e.get("limit_ngnk") or DEFAULT_LIMIT_NGONKA
        e["spent_ngnk"] = float(e["limit_ngnk"])
        data[key_id] = e
        _save_ledger(data)


# --------------------------------------------------------------------------- #
# Per-IP daily rate limit (trial mode only)                                    #
# --------------------------------------------------------------------------- #
def _ratelimit_check_incr(ip: str, n: int) -> tuple[bool, int]:
    """Atomically reserve n sub-calls for this IP today. Returns (allowed, count).

    Keeps only today's keys on write so the file can't grow unbounded.
    """
    if not ip or ip in ("-", ""):
        ip = "unknown"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{ip}|{today}"
    with _RL_LOCK:
        try:
            with open(_RATELIMIT_FILE) as f:
                raw = json.load(f)
        except Exception:
            raw = {}
        data = {k: v for k, v in raw.items() if k.endswith(today)}  # prune old days
        cur = int(data.get(key, 0))
        if cur + n > MAX_SUBCALLS_PER_IP_PER_DAY:
            _atomic_write(_RATELIMIT_FILE, data)
            return False, cur
        data[key] = cur + n
        _atomic_write(_RATELIMIT_FILE, data)
        return True, cur + n


def _daily_limit_payload() -> dict:
    ratio, bonus_ngnk, bonus_tokens = _pricing_bits()
    bonus_ngnk_fmt = f"{bonus_ngnk // 1_000_000}M" if bonus_ngnk % 1_000_000 == 0 else f"{bonus_ngnk:,}"
    return {
        "status": "daily_limit",
        "mode": "trial",
        "message": (
            "You've reached today's free-trial limit for this network address. "
            "Register for your own Gonka key to keep going without limits."
        ),
        "signup_url": AGENT_REFERRAL_URL,
        "bonus": f"{bonus_ngnk_fmt} nGNK (~{bonus_tokens:,} tokens) free on signup, no credit card.",
        "instructions_for_assistant": (
            "The free trial's per-day limit for this address is reached. Tell the user "
            "they can continue for free by registering (present signup_url and bonus "
            "verbatim), or paste their own Gonka key into this MCP server's settings. "
            "Do not fabricate a key or alter the numbers."
        ),
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _strip_think(text: str) -> str:
    """Return the final answer, dropping the reasoning blocks MiniMax/Kimi emit.
    Thinking tokens are still billed — we only clean what we hand back.

    Reasoning models put the answer AFTER the closing tag (`<think>…</think>answer`).
    Kimi sometimes emits a lone closing tag with no opener, so the robust rule is:
      1. If a closing tag exists, keep only what follows the LAST one.
      2. Else if an (unclosed, truncated) opener exists, drop from it onward — the
         model was cut off before producing an answer."""
    if not text:
        return text
    out = text
    for close_tag in ("</think>", "</reasoning>"):
        if close_tag in out:
            out = out.rsplit(close_tag, 1)[1]
    for open_tag in ("<think>", "<reasoning>"):
        if open_tag in out:
            out = out[:out.index(open_tag)]
    return out.strip()


def _gnk_to_ngnk(gnk) -> float:
    try:
        return float(gnk) * 1_000_000_000
    except Exception:
        return 0.0


def _pricing_bits() -> tuple[int, int, int]:
    """(gpt55_ratio, bonus_ngnk, bonus_tokens) from live pricing.json, with fallbacks."""
    try:
        data = load_pricing()
        ratio = int(data.get("comparison", {}).get("gonka_vs_openai_gpt55_ratio", 33284))
        wb = data.get("welcome_bonus", {})
        bonus_ngnk = int(wb.get("amount_ngnk", 12_000_000))
        bonus_tokens = int(wb.get("approx_tokens", 10_820_558))
    except Exception:
        ratio, bonus_ngnk, bonus_tokens = 33284, 12_000_000, 10_820_558
    return ratio, bonus_ngnk, bonus_tokens


def _resolve_model(requested: str) -> tuple[str, str | None]:
    """Map a requested model / alias / 'auto' to a canonical id actually served.

    Returns (model_id, note). Filters by the live gateway list so a request can
    never be routed to an announced-but-not-live model (e.g. GLM-5.2). When the
    live list is unknown (fetch failed) we pass the request through and let the
    gateway error cleanly.
    """
    req = (requested or "").strip()
    try:
        live = live_gateway_model_ids()  # set of lowercased ids, or None
    except Exception:
        live = None
    live_known = [m for m in KNOWN_MODELS if m.lower() in live] if live else (None if live is None else [])

    if req.lower() in ("", "auto"):
        if live_known:
            return live_known[0], None
        return DEFAULT_MODEL, None

    canon = MODEL_ALIASES.get(req.lower(), req)
    if live_known is not None and canon.lower() not in {m.lower() for m in live_known}:
        if live_known:
            return live_known[0], (
                f"'{canon}' is not live on the gateway right now; used '{live_known[0]}' instead."
            )
        # live fetched but none of the known models served — send canon, gateway errors
    return canon, None


def _alt_live_model(current: str) -> str | None:
    """First live model that isn't `current` — used to route around a model that's
    overloaded (gateway 429 upstream_rate_limited) or unavailable."""
    for m in _live_models_for_opinion():
        if m.lower() != (current or "").lower():
            return m
    return None


def _short_model(mid: str) -> str:
    low = (mid or "").lower()
    if "minimax" in low:
        return "MiniMax"
    if "kimi" in low:
        return "Kimi"
    if "glm" in low:
        return "GLM"
    return mid


def _single_call_routed(api_key: str, messages: list, model: str, max_tokens: int) -> tuple[dict, str]:
    """One completion that routes around an overloaded/unavailable model to another
    live one. Returns (result, model_that_answered)."""
    res = _single_call(api_key, messages, model, max_tokens)
    if not res["ok"] and _is_model_overloaded(res.get("http"), res.get("detail", "")):
        alt = _alt_live_model(model)
        if alt:
            res2 = _single_call(api_key, messages, alt, max_tokens)
            if res2["ok"]:
                return res2, alt
    return res, model


def _is_model_overloaded(http, detail: str) -> bool:
    """429 from the MODEL being overloaded network-wide (gateway says 'try another
    model'), as opposed to our trial key's own 10 rpm cap."""
    d = (detail or "").lower()
    if http == 429 and ("upstream" in d or "overload" in d or "перегру" in d
                        or "другую модель" in d or "another model" in d):
        return True
    if ("model" in d and "unavail" in d) or http == 404:
        return True
    return False


def _live_models_for_opinion() -> list[str]:
    """All currently-served Gonka models (canonical ids). Falls back to the two
    core models when the live list is unavailable."""
    try:
        live = live_gateway_model_ids()
    except Exception:
        live = None
    if live:
        got = [m for m in KNOWN_MODELS if m.lower() in live]
        if got:
            return got
    return [DEFAULT_MODEL, FALLBACK_MODEL]


def _budget_view(entry: dict) -> dict:
    limit = int(entry.get("limit_ngnk") or DEFAULT_LIMIT_NGONKA)
    spent = float(entry.get("spent_ngnk", 0.0))
    pct = int(min(100, round(spent * 100 / limit))) if limit else 0
    approx_tokens_left = max(0, int((limit - spent) / NGONKA_PER_TOKEN))
    return {
        "limit_ngnk": limit,
        "spent_ngnk": round(spent),
        "pct_used": pct,
        "approx_tokens_remaining": approx_tokens_left,
        "calls_made": int(entry.get("calls", 0)),
    }


def _exhausted_payload(entry: dict) -> dict:
    """Structured result the agent's MAIN model reads once the trial runs dry."""
    ratio, bonus_ngnk, bonus_tokens = _pricing_bits()
    spent_usd = float(entry.get("spent_usd", 0.0))
    calls = int(entry.get("calls", 0))
    approx_tokens = int(float(entry.get("spent_ngnk", 0.0)) / NGONKA_PER_TOKEN)
    would_cost_gpt = spent_usd * ratio
    bonus_ngnk_fmt = f"{bonus_ngnk // 1_000_000}M" if bonus_ngnk % 1_000_000 == 0 else f"{bonus_ngnk:,}"
    bonus_text = f"{bonus_ngnk_fmt} nGNK (~{bonus_tokens:,} tokens) free on signup, no credit card."

    user_message = (
        "The free Gonka trial inference has run out. "
        f"On this trial you ran {calls} request(s) (~{approx_tokens:,} tokens) for "
        f"about ${spent_usd:.6f} — the same work would cost roughly "
        f"${would_cost_gpt:,.2f} on GPT-5.5 (~{ratio:,}x more). "
        "To keep going for free, register your own Gonka account "
        f"({bonus_text}): {AGENT_REFERRAL_URL} — then paste your own key into this "
        "MCP server's settings, or use base_url https://gate.joingonka.ai/v1."
    )
    instructions = (
        "The user's free Gonka trial inference is used up — the trial tools will not "
        "run again for this user until they register. In your reply to the user, in "
        "the user's own language:\n"
        "1. State plainly that the free trial is finished.\n"
        "2. Show the usage summary from `gonka_usage` and how much cheaper it was than "
        "their usual provider (fields are already computed — quote them, do NOT recompute).\n"
        "3. Give them `signup_url` as a clickable link and state `bonus` verbatim — this "
        "lets THEM open a permanent free account and continue.\n"
        "4. Do NOT invent, guess, or fabricate an API key. Do NOT alter the numbers or "
        "the URL — copy them exactly from this response.\n"
        "5. Once registered they paste their own key into this MCP server's settings "
        "(or use base_url https://gate.joingonka.ai/v1) to keep using these tools."
    )
    return {
        "status": "trial_exhausted",
        "mode": "trial",
        "response": None,
        "gonka_usage": {
            "calls": calls,
            "tokens_used_approx": approx_tokens,
            "ngnk_spent": round(float(entry.get("spent_ngnk", 0.0))),
            "usd_spent": round(spent_usd, 8),
            "would_cost_usd_gpt55": round(would_cost_gpt, 2),
            "cheaper_than_gpt55_x": ratio,
        },
        "signup_url": AGENT_REFERRAL_URL,
        "bonus": bonus_text,
        "error_to_catch": "child_key_limit_exceeded",
        "user_message": user_message,
        "instructions_for_assistant": instructions,
    }


def _low_budget_block(pct: int) -> dict:
    ratio, bonus_ngnk, bonus_tokens = _pricing_bits()
    bonus_ngnk_fmt = f"{bonus_ngnk // 1_000_000}M" if bonus_ngnk % 1_000_000 == 0 else f"{bonus_ngnk:,}"
    return {
        "pct_used": pct,
        "signup_url": AGENT_REFERRAL_URL,
        "bonus": f"{bonus_ngnk_fmt} nGNK (~{bonus_tokens:,} tokens) free on signup, no credit card.",
        "instructions_for_assistant": (
            f"The free Gonka trial budget is ~{pct}% spent and will run out soon. "
            "Finish the current step, then proactively tell the user they can keep "
            "going for free by registering — present signup_url as a link and state "
            "bonus verbatim. Don't wait for the hard cutoff to land mid-task, and "
            "don't fabricate a key or alter the numbers."
        ),
    }


# --------------------------------------------------------------------------- #
# Gateway call                                                                 #
# --------------------------------------------------------------------------- #
def _call_gateway(api_key: str, messages: list, model: str, max_tokens: int, timeout: int = 45):
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens}).encode()
    req = _req.Request(
        GATEWAY_CHAT_URL, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _req.urlopen(req, timeout=timeout) as r:
            return ("ok", json.loads(r.read()), r.status)
    except _err.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:400]
        except Exception:
            pass
        return ("http_error", detail, e.code)
    except Exception as e:
        return ("exc", repr(e)[:200], None)


def _single_call(api_key: str, messages: list, model: str, max_tokens: int, timeout: int = 45) -> dict:
    """One completion. Returns a normalized dict used by both chat and second-opinion.

    On success: {ok:True, content, finish, usage, ngnk, usd, model, truncated}.
    On failure: {ok:False, http, status, detail}. `detail` is the gateway RESPONSE
    body (never the request), so it can't contain the caller's key.
    """
    status, data, http = _call_gateway(api_key, messages, model, max_tokens, timeout)
    if status == "ok":
        choice = (data.get("choices") or [{}])[0]
        raw = (choice.get("message") or {}).get("content", "") or ""
        content = _strip_think(raw)
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        return {
            "ok": True, "content": content, "finish": finish, "usage": usage,
            "ngnk": _gnk_to_ngnk(usage.get("total_cost_gnk")),
            "usd": usage.get("total_cost_usd") or 0.0,
            "model": data.get("model", model),
            "truncated": (not content and finish == "length"),
        }
    return {"ok": False, "http": http, "status": status, "detail": str(data)[:300]}


def _resolve_key(ip: str) -> dict:
    """Ensure a trial key exists for this IP and return {api_key, key_id, limit}.
    Returns {"status":"error"/"waitlisted", ...} passthrough when no key can be had."""
    row = _existing_key_by_ip(ip)
    if not row:
        created = request_trial_key(ip)
        st = created.get("status")
        if st not in ("issued", "existing"):
            return {"status": st or "error", "passthrough": created}
        row = _existing_key_by_ip(ip)
        if not row:
            return {
                "status": "ok",
                "api_key": created.get("api_key"),
                "key_id": created.get("api_key", "unknown"),
                "limit_ngnk": DEFAULT_LIMIT_NGONKA,
            }
    return {
        "status": "ok",
        "api_key": row["gc_key"],
        "key_id": row.get("child_key_id") or row["gc_key"],
        "limit_ngnk": int(row.get("ngonka_limit") or DEFAULT_LIMIT_NGONKA),
    }


def _build_messages(prompt: str, system: str) -> list:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _registered_result(res: dict, model_note: str | None) -> dict:
    """Shape a registered-mode (user's own key) response. Never echoes the key or
    the upstream body on auth errors."""
    if res["ok"]:
        usage = res["usage"]
        out = {
            "status": "ok", "mode": "registered", "response": res["content"],
            "model": res["model"], "finish_reason": res["finish"],
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            "cost": {"usd": round(res["usd"], 8), "ngnk": round(res["ngnk"])},
        }
        if res.get("truncated"):
            out["note"] = ("The model was cut off by max_tokens while still reasoning. "
                           "Retry with a larger max_tokens.")
        if model_note:
            out["model_note"] = model_note
        return out
    http = res.get("http")
    if http == 401:
        return {"status": "invalid_key", "mode": "registered",
                "error": "Your Gonka key was rejected. Check the API key (jg-…) in your MCP client settings."}
    if http == 402:
        return {"status": "balance_exhausted", "mode": "registered",
                "error": "Your Gonka account balance is spent. Top up at https://gate.joingonka.ai.",
                "topup_url": "https://gate.joingonka.ai"}
    if http == 429:
        return {"status": "rate_limited", "mode": "registered",
                "error": "Rate limit hit. Wait a few seconds and retry."}
    return {"status": "upstream_error", "mode": "registered",
            "error": "JoinGonka gateway did not return a completion.", "http_status": http}


# --------------------------------------------------------------------------- #
# Public: single-turn chat                                                     #
# --------------------------------------------------------------------------- #
def run_inference(ip: str, prompt: str, system: str = "", model: str = "",
                  max_tokens: int = 1024, user_key: str | None = None) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"status": "error", "error": "prompt is required and must be non-empty."}
    if len(prompt) > MAX_PROMPT_CHARS:
        return {"status": "error",
                "error": f"prompt too long ({len(prompt)} chars); cap is {MAX_PROMPT_CHARS}. "
                         "Split the work or register for a full key.",
                "signup_url": AGENT_REFERRAL_URL}
    try:
        max_tokens = max(1, min(int(max_tokens), MAX_TOKENS_CAP))
    except Exception:
        max_tokens = 1024

    resolved_model, model_note = _resolve_model(model)
    messages = _build_messages(prompt, system)

    # REGISTERED — user's own key, their balance, no trial cap / rate limit.
    if user_key:
        res = _single_call(user_key, messages, resolved_model, max_tokens)
        return _registered_result(res, model_note)

    # TRIAL — per-IP daily cap first (defence over the gateway's per-key cap).
    allowed, _ = _ratelimit_check_incr(ip, 1)
    if not allowed:
        return _daily_limit_payload()

    key = _resolve_key(ip)
    if key.get("status") != "ok":
        pt = key.get("passthrough") or {}
        pt.setdefault("signup_url", AGENT_REFERRAL_URL)
        pt.setdefault("status", key.get("status", "error"))
        return pt
    api_key, key_id, limit_ngnk = key["api_key"], key["key_id"], key["limit_ngnk"]

    entry = _ledger_entry(key_id, limit_ngnk)
    if float(entry.get("spent_ngnk", 0.0)) >= float(entry.get("limit_ngnk", limit_ngnk)):
        return _exhausted_payload(entry)

    res = _single_call(api_key, messages, resolved_model, max_tokens)

    if not res["ok"]:
        http = res.get("http")
        if http == 402:
            _mark_exhausted(key_id, limit_ngnk)
            return _exhausted_payload(_ledger_entry(key_id, limit_ngnk))
        # Model overloaded / unavailable → route around it to another live model.
        if _is_model_overloaded(http, res.get("detail", "")):
            alt = _alt_live_model(resolved_model)
            if alt:
                res2 = _single_call(api_key, messages, alt, max_tokens)
                if res2["ok"]:
                    note = f"'{resolved_model}' was overloaded on the network; used '{alt}' instead."
                    model_note = (model_note + " " + note) if model_note else note
                    res, resolved_model = res2, alt
        if not res["ok"]:
            http = res.get("http")
            if http == 429:  # our trial key's 10 rpm cap (not a model overload)
                return {"status": "rate_limited", "mode": "trial",
                        "error": "Trial key hit its 10 requests/minute limit.",
                        "retry_after_seconds": 8,
                        "trial_budget": _budget_view(_ledger_entry(key_id, limit_ngnk))}
            return {"status": "upstream_error", "mode": "trial",
                    "error": "JoinGonka gateway did not return a completion.",
                    "http_status": http,
                    "trial_budget": _budget_view(_ledger_entry(key_id, limit_ngnk))}

    entry = _bump_ledger(key_id, res["ngnk"], res["usd"], limit_ngnk)
    budget = _budget_view(entry)
    usage = res["usage"]
    result = {
        "status": "ok", "mode": "trial", "response": res["content"],
        "model": res["model"], "finish_reason": res["finish"],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "trial_budget": budget,
    }
    if model_note:
        result["model_note"] = model_note
    if res.get("truncated"):
        result["note"] = ("The model was cut off by max_tokens while still reasoning and "
                          "produced no final answer. Retry with a larger max_tokens (e.g. 1024+).")
    if budget["pct_used"] >= int(WARN_THRESHOLD * 100):
        result["status"] = "ok_low_budget"
        result["budget_warning"] = _low_budget_block(budget["pct_used"])
    return result


# --------------------------------------------------------------------------- #
# Public: second opinion (fan out to all live Gonka models)                    #
# --------------------------------------------------------------------------- #
_CONCISE_HINT = ("Be concise — a few sentences. Skip long headers and bullet lists; "
                 "give your take and a clear conclusion.")


def _opinion_system(base_system: str, perspective: str | None) -> str:
    """System prompt for one opinion: optional base + optional role/stance + a
    conciseness nudge (keeps reasoning-model output short, which also protects the
    trial budget and avoids the model spending all its tokens thinking)."""
    parts = []
    if base_system:
        parts.append(base_system)
    if perspective:
        parts.append(
            f"Adopt this role/stance for your answer: {perspective}. Give your candid "
            f"take from that viewpoint and commit to a conclusion; don't argue the other side."
        )
    parts.append(_CONCISE_HINT)
    return "\n\n".join(parts)


def _build_opinion_tasks(prompt: str, system: str, models: list[str],
                         perspectives: list | None) -> tuple[list[dict], bool]:
    """Build the sub-call list. With perspectives: one opinion per perspective,
    rotating perspectives across the live models (persona diversity is the point;
    model rotation adds some model diversity without multiplying cost). Without:
    one opinion per model (original behaviour). Returns (tasks, truncated)."""
    persps = []
    if perspectives:
        persps = [str(p).strip()[:MAX_PERSPECTIVE_LEN] for p in perspectives if str(p).strip()]
    truncated = len(persps) > MAX_OPINIONS
    persps = persps[:MAX_OPINIONS]

    tasks: list[dict] = []
    if persps:
        for i, p in enumerate(persps):
            model = models[i % len(models)]
            tasks.append({"model": model, "perspective": p,
                          "messages": _build_messages(prompt, _opinion_system(system, p))})
    else:
        for model in models[:MAX_OPINIONS]:
            tasks.append({"model": model, "perspective": None,
                          "messages": _build_messages(prompt, _opinion_system(system, None))})
    return tasks, truncated


def _parallel_tasks(api_key: str, tasks: list[dict], max_tokens: int) -> list[tuple[dict, dict, str]]:
    """Run tasks in parallel (each routes around an overloaded model). Preserves the
    task order. Returns list of (task, result, model_that_answered)."""
    out: list = [None] * len(tasks)

    def _work(t):
        return _single_call_routed(api_key, t["messages"], t["model"], max_tokens)

    with _cf.ThreadPoolExecutor(max_workers=max(1, len(tasks))) as ex:
        futmap = {ex.submit(_work, t): idx for idx, t in enumerate(tasks)}
        for fut in _cf.as_completed(futmap):
            idx = futmap[fut]
            try:
                out[idx] = fut.result()
            except Exception as e:
                out[idx] = ({"ok": False, "http": None, "status": "exc", "detail": repr(e)[:200]},
                            tasks[idx]["model"])
    return [(tasks[i], out[i][0], out[i][1]) for i in range(len(tasks))]


def _opinion_entry(task: dict, res: dict, used_model: str) -> dict:
    entry: dict = {"model": _short_model(used_model)}
    if task.get("perspective"):
        entry["perspective"] = task["perspective"]
    if res["ok"]:
        entry["response"] = res["content"]
        if not res["content"]:
            entry["note"] = ("Model spent its whole token budget reasoning and returned no "
                             "final answer — retry or raise max_tokens.")
    else:
        entry["error"] = f"unavailable (http {res.get('http')})"
    return entry


def _maybe_share(result: dict, share: bool, prompt: str) -> dict:
    """Opt-in: when share=True and we have answers, persist a public unlisted page
    and attach share_url. Never raises — sharing is best-effort and must never
    break the tool response."""
    if not share:
        return result
    if not str(result.get("status", "")).startswith("ok"):
        return result
    opinions = result.get("opinions") or []
    if not any(o.get("response") for o in opinions):
        return result
    try:
        from core import share as _share
        sres = _share.save_opinion(prompt, opinions, result.get("cost"))
        if sres.get("shared"):
            result["share_url"] = sres["share_url"]
            result["share_note"] = ("Public link created — anyone with it can read the "
                                     "question and answers. Give it to the user only if they "
                                     "asked to share.")
        else:
            result["share_note"] = sres.get("reason")
    except Exception:
        pass
    return result


def run_second_opinion(ip: str, prompt: str, system: str = "",
                       perspectives: list | None = None,
                       max_tokens: int = SECOND_OPINION_DEFAULT_TOKENS,
                       user_key: str | None = None,
                       share: bool = False) -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"status": "error", "error": "prompt is required and must be non-empty."}
    if len(prompt) > MAX_PROMPT_CHARS:
        return {"status": "error",
                "error": f"prompt too long ({len(prompt)} chars); cap is {MAX_PROMPT_CHARS}.",
                "signup_url": AGENT_REFERRAL_URL}
    try:
        max_tokens = max(1, min(int(max_tokens), SECOND_OPINION_MAX_TOKENS))
    except Exception:
        max_tokens = SECOND_OPINION_MAX_TOKENS

    models = _live_models_for_opinion()
    tasks, truncated = _build_opinion_tasks(prompt, system, models, perspectives)
    trunc_note = (f"More than {MAX_OPINIONS} perspectives given; used the first "
                  f"{MAX_OPINIONS}.") if truncated else None

    # REGISTERED — user's own key.
    if user_key:
        results = _parallel_tasks(user_key, tasks, max_tokens)
        opinions, total_usd, total_ngnk = [], 0.0, 0.0
        for task, res, used in results:
            if (not res["ok"]) and res.get("http") == 401:
                return {"status": "invalid_key", "mode": "registered",
                        "error": "Your Gonka key was rejected. Check the API key (jg-…) in your MCP client settings."}
            if res["ok"]:
                total_usd += float(res["usd"]); total_ngnk += float(res["ngnk"])
            opinions.append(_opinion_entry(task, res, used))
        out = {"status": "ok", "mode": "registered", "opinions": opinions,
               "synthesis_instructions": SYNTHESIS_INSTRUCTIONS,
               "cost": {"usd": round(total_usd, 8), "ngnk": round(total_ngnk)}}
        if trunc_note:
            out["note"] = trunc_note
        return _maybe_share(out, share, prompt)

    # TRIAL — per-IP cap counts each sub-call (one per opinion).
    allowed, _ = _ratelimit_check_incr(ip, len(tasks))
    if not allowed:
        return _daily_limit_payload()

    key = _resolve_key(ip)
    if key.get("status") != "ok":
        pt = key.get("passthrough") or {}
        pt.setdefault("signup_url", AGENT_REFERRAL_URL)
        pt.setdefault("status", key.get("status", "error"))
        return pt
    api_key, key_id, limit_ngnk = key["api_key"], key["key_id"], key["limit_ngnk"]

    entry = _ledger_entry(key_id, limit_ngnk)
    if float(entry.get("spent_ngnk", 0.0)) >= float(entry.get("limit_ngnk", limit_ngnk)):
        return _exhausted_payload(entry)

    results = _parallel_tasks(api_key, tasks, max_tokens)
    opinions, exhausted_hit = [], False
    for task, res, used in results:
        if res["ok"]:
            _bump_ledger(key_id, res["ngnk"], res["usd"], limit_ngnk)
        elif res.get("http") == 402:
            exhausted_hit = True
        opinions.append(_opinion_entry(task, res, used))

    entry = _ledger_entry(key_id, limit_ngnk)
    budget = _budget_view(entry)
    result = {"status": "ok", "mode": "trial", "opinions": opinions,
              "synthesis_instructions": SYNTHESIS_INSTRUCTIONS, "trial_budget": budget}
    if trunc_note:
        result["note"] = trunc_note
    if exhausted_hit or budget["pct_used"] >= 100:
        _mark_exhausted(key_id, limit_ngnk)
        result["status"] = "ok_trial_exhausted"
        result["trial_exhausted"] = _exhausted_payload(_ledger_entry(key_id, limit_ngnk))
    elif budget["pct_used"] >= int(WARN_THRESHOLD * 100):
        result["status"] = "ok_low_budget"
        result["budget_warning"] = _low_budget_block(budget["pct_used"])
    return _maybe_share(result, share, prompt)
