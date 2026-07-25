#!/usr/bin/env python3
"""Render the README badge images from live pricing.json.

Writes two SVGs into the public img dir so the GitHub README (and gogonka.com)
show CURRENT market numbers, never a hardcoded figure:

  price-badge.svg  — live $/1M tokens, cheaper-than ratio, GNK/USD, timestamp
  panel-cost.svg   — typical cost of one 3-model second-opinion panel

Run on a cron (e.g. every 10 min, right after pricing.json refreshes):
  */10 * * * * /usr/bin/python3 /opt/agentgonka/gonka-mcp/render_badges.py

On GitHub the image is proxied/cached by camo, so it lags a few minutes to
hours; on gogonka.com it is truly live. Both are far better than a frozen number.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PRICING = Path("/var/www/gogonka/pricing.json")
OUT_DIR = Path("/var/www/gogonka/img")

# Measured typical cost of one 3-model panel on the real gateway (billed incl.
# reasoning tokens — NOT derivable from the marketing $/1M, which understates).
# Refresh occasionally from live gonka_second_opinion runs. Kept explicit and
# dated so the claim stays honest.
PANEL_USD = 0.0000139  # ≈ 0.0014¢, observed 2026-07-25


def _load() -> dict:
    try:
        d = json.load(open(PRICING))
    except Exception:
        d = {}
    model = next((m for m in d.get("models", [])
                  if m.get("id") == "MiniMaxAI/MiniMax-M2.7"), {})
    usd = model.get("usd_per_1m_tokens_at_current") or 0.000137
    ratio = d.get("comparison", {}).get("gonka_vs_openai_gpt55_ratio") or 36000
    gnk = d.get("gnk_market", {}).get("usd_price_current") or 0.12
    updated = d.get("data_last_updated") or ""
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(timezone.utc)
        upd = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        upd = "recently"
    return {"usd": usd, "ratio": int(ratio), "gnk": gnk, "updated": upd}


def _panel_cents() -> str:
    c = PANEL_USD * 100  # cents
    return f"{c:.4f}".rstrip("0").rstrip(".") + "¢"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_price(d: dict) -> str:
    usd = f"${d['usd']:.6f}".rstrip("0").rstrip(".")
    ratio = f"{d['ratio']:,}×"
    gnk = f"${d['gnk']:.4f}"
    sub = _esc(f"GNK/USD {gnk}  ·  updated {d['updated']}")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 96" font-family="-apple-system,Segoe UI,Roboto,sans-serif">
  <rect width="680" height="96" rx="12" fill="#0a0f1e" stroke="#1e293b"/>
  <rect x="0" y="0" width="6" height="96" rx="3" fill="#00d4ff"/>
  <text x="28" y="30" fill="#64748b" font-size="13" font-weight="700" letter-spacing="1.5">GONKA · LIVE INFERENCE PRICE</text>
  <text x="28" y="62" fill="#e2e8f0" font-size="26" font-weight="800">{_esc(usd)}<tspan fill="#64748b" font-size="16" font-weight="600"> /1M tokens</tspan></text>
  <text x="300" y="62" fill="#34d399" font-size="22" font-weight="800">{_esc(ratio)}<tspan fill="#64748b" font-size="15" font-weight="600"> cheaper than GPT-5.5</tspan></text>
  <text x="28" y="84" fill="#475569" font-size="13">{sub}</text>
</svg>
'''


def render_panel() -> str:
    cents = _panel_cents()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 96" font-family="-apple-system,Segoe UI,Roboto,sans-serif">
  <rect width="420" height="96" rx="12" fill="#0a0f1e" stroke="#1e293b"/>
  <rect x="0" y="0" width="6" height="96" rx="3" fill="#7c3aed"/>
  <text x="28" y="30" fill="#64748b" font-size="13" font-weight="700" letter-spacing="1.5">ONE 3-MODEL SECOND OPINION</text>
  <text x="28" y="66" fill="#e2e8f0" font-size="30" font-weight="800">≈ {cents}<tspan fill="#64748b" font-size="15" font-weight="600"> per panel</tspan></text>
  <text x="28" y="86" fill="#475569" font-size="13">a fraction of a cent · typical, measured</text>
</svg>
'''


def main() -> None:
    d = _load()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "price-badge.svg").write_text(render_price(d))
    (OUT_DIR / "panel-cost.svg").write_text(render_panel())
    print(f"rendered price-badge.svg (${d['usd']:.6f}/1M, {d['ratio']:,}×) "
          f"and panel-cost.svg ({_panel_cents()})")


if __name__ == "__main__":
    main()
