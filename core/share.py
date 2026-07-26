"""Public shareable second-opinion pages — the opt-in viral loop.

A page is created ONLY when the caller passes share=true to gonka_second_opinion.
We persist an allowlisted record (question + answers + model names + cost) to
OPINIONS_DIR and serve it as a public *unlisted* page at gogonka.com/o/<slug>.

Privacy guarantees (see plan):
  * Never persist api_key / user_key / key_id / IP — strict field allowlist.
  * Refuse to publish if the text looks like it carries an API key / secret.
  * Soft-redact emails.
  * Random unguessable slug (secrets.token_urlsafe) + robots noindex.

The page carries a live "try it" demo (trial path). To stop a viral page from
draining the shared trial pool with cold traffic, the demo is guarded by a global
daily nGNK cap + kill-switch (defence-in-depth over the per-IP trial cap).
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone

from core.pricing import AGENT_REFERRAL_URL

# --------------------------------------------------------------------------- #
# Config (all env-tunable)                                                     #
# --------------------------------------------------------------------------- #
OPINIONS_DIR   = os.environ.get("OPINIONS_DIR", "/opt/agentgonka/opinions")
SHARE_BASE_URL = os.environ.get("SHARE_BASE_URL", "https://gogonka.com/o").rstrip("/")
_MAX_STORED    = int(os.environ.get("OPINIONS_MAX_STORED", "5000"))
_TTL_DAYS      = int(os.environ.get("OPINIONS_TTL_DAYS", "30"))

# Live-demo budget fuse (defence-in-depth over the per-IP trial cap).
DEMO_ENABLED        = os.environ.get("DEMO_ENABLED", "1").lower() not in ("0", "false", "no")
DEMO_DAILY_NGNK_CAP = float(os.environ.get("DEMO_DAILY_NGNK_CAP", "2000000"))  # ~100k tokens/day
DEMO_MAX_TOKENS     = int(os.environ.get("DEMO_MAX_TOKENS", "512"))
_NGNK_PER_TOKEN     = 19.8  # matches core.proxy.NGONKA_PER_TOKEN

_DEMO_BUDGET_FILE = os.path.join(OPINIONS_DIR, "_demo_budget.json")
_STATS_FILE       = os.path.join(OPINIONS_DIR, "_stats.json")
_LOCK = threading.Lock()

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

# Hard secrets → refuse publication. Emails → soft-redact.
_HARD_SECRET = re.compile(
    r"(?:(?:jg|gc|gp|sk|rpnd|pk|xai|ghp|gho|glpat|AKIA|AIza)[-_][A-Za-z0-9_-]{16,})"
    r"|(?:bearer\s+[A-Za-z0-9._-]{20,})",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


# --------------------------------------------------------------------------- #
# Storage helpers                                                             #
# --------------------------------------------------------------------------- #
def _ensure_dir() -> None:
    os.makedirs(OPINIONS_DIR, exist_ok=True)


def _atomic_write(path: str, data: dict) -> None:
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(dir=OPINIONS_DIR, prefix=".tmp-", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _redact(text: str) -> str:
    if not text:
        return text or ""
    return _EMAIL.sub("[email]", text)


def _has_hard_secret(text: str) -> bool:
    return bool(text) and bool(_HARD_SECRET.search(text))


# --------------------------------------------------------------------------- #
# Save / load a shared opinion                                                #
# --------------------------------------------------------------------------- #
def save_opinion(prompt: str, opinions: list, cost: dict | None = None) -> dict:
    """Persist an allowlisted record. Returns
    {"shared": True, "slug", "share_url"} or {"shared": False, "reason"}."""
    blob = (prompt or "") + "\n" + "\n".join((o.get("response") or "") for o in (opinions or []))
    if _has_hard_secret(blob):
        return {"shared": False,
                "reason": "Not shared — the question or an answer looks like it contains "
                          "an API key or secret."}
    safe_opinions = []
    for o in (opinions or []):
        c: dict = {"model": o.get("model")}
        if o.get("perspective"):
            c["perspective"] = o["perspective"]
        if o.get("response") is not None:
            c["response"] = _redact(o.get("response") or "")
        if o.get("note"):
            c["note"] = o["note"]
        if o.get("error"):
            c["error"] = o["error"]
        safe_opinions.append(c)

    slug = secrets.token_urlsafe(8)
    record = {
        "slug": slug,
        "prompt": _redact(prompt or ""),
        "opinions": safe_opinions,
        "cost": cost or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with _LOCK:
            _atomic_write(os.path.join(OPINIONS_DIR, slug + ".json"), record)
            _bump_stats()
            _rotate()
    except Exception:
        return {"shared": False, "reason": "Could not create the share page (storage error)."}
    return {"shared": True, "slug": slug, "share_url": f"{SHARE_BASE_URL}/{slug}"}


def load_opinion(slug: str) -> dict | None:
    if not slug or not _SLUG_RE.match(slug):
        return None
    rec = _read_json(os.path.join(OPINIONS_DIR, slug + ".json"))
    return rec or None


def _rotate() -> None:
    try:
        files = [f for f in os.listdir(OPINIONS_DIR)
                 if f.endswith(".json") and not f.startswith(("_", ".tmp"))]
        paths = [(os.path.join(OPINIONS_DIR, f), 0.0) for f in files]
        now = time.time()
        alive = []
        for p, _ in paths:
            try:
                mt = os.path.getmtime(p)
            except Exception:
                continue
            if now - mt > _TTL_DAYS * 86400:
                try:
                    os.remove(p)
                except Exception:
                    pass
            else:
                alive.append((p, mt))
        if len(alive) > _MAX_STORED:
            alive.sort(key=lambda x: x[1])
            for p, _ in alive[:len(alive) - _MAX_STORED]:
                try:
                    os.remove(p)
                except Exception:
                    pass
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Social-proof counter (shared pages created per day)                         #
# --------------------------------------------------------------------------- #
def _bump_stats() -> None:
    data = _read_json(_STATS_FILE)
    d = _today()
    data[d] = int(data.get(d, 0)) + 1
    # keep only the most recent ~14 day keys
    for k in sorted(data.keys())[:-14]:
        data.pop(k, None)
    _atomic_write(_STATS_FILE, data)


def today_count() -> int:
    return int(_read_json(_STATS_FILE).get(_today(), 0))


# --------------------------------------------------------------------------- #
# Live-demo budget fuse                                                       #
# --------------------------------------------------------------------------- #
def _demo_spent_today() -> float:
    data = _read_json(_DEMO_BUDGET_FILE)
    if data.get("date") == _today():
        return float(data.get("spent_ngnk", 0.0))
    return 0.0


def demo_allowed() -> tuple[bool, float, float]:
    """(allowed, spent_ngnk_today, cap). Honors kill-switch + daily cap."""
    if not DEMO_ENABLED:
        return (False, 0.0, DEMO_DAILY_NGNK_CAP)
    spent = _demo_spent_today()
    return (spent < DEMO_DAILY_NGNK_CAP, spent, DEMO_DAILY_NGNK_CAP)


def demo_add_spend(ngnk: float) -> None:
    with _LOCK:
        _atomic_write(_DEMO_BUDGET_FILE,
                      {"date": _today(), "spent_ngnk": _demo_spent_today() + float(ngnk or 0.0)})


def demo_estimate_ngnk(n_opinions: int, max_tokens: int) -> float:
    """Conservative upper-bound estimate (over-counts → fuse trips earlier = safe)."""
    return max(1, n_opinions) * max_tokens * _NGNK_PER_TOKEN


# --------------------------------------------------------------------------- #
# HTML rendering                                                              #
# --------------------------------------------------------------------------- #
_CSS = """
*{box-sizing:border-box}
body{background:#0a0f1e;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;
line-height:1.6;max-width:760px;margin:0 auto;padding:2rem 1.1rem}
a{color:#00d4ff;text-decoration:none}
.brand{font-size:.8rem;letter-spacing:.04em;color:#64748b;text-transform:uppercase;margin-bottom:.5rem}
.brand b{color:#00d4ff}
h1{font-size:1.35rem;line-height:1.35;margin:.2rem 0 1rem;font-weight:650}
.meta{color:#64748b;font-size:.82rem;margin-bottom:1.4rem}
.card{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:1rem 1.15rem;margin:.9rem 0}
.card .who{display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem}
.badge{background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.25);color:#7fe7ff;
font-size:.72rem;font-weight:700;padding:.16em .6em;border-radius:999px}
.persp{color:#a78bfa;font-size:.8rem}
.resp{white-space:pre-wrap;color:#cbd5e1;font-size:.95rem}
.resp.err{color:#f87171}
.demo{background:#0d1424;border:1px solid rgba(0,212,255,.22);border-radius:14px;padding:1.15rem;margin:1.6rem 0}
.demo h2{font-size:1.02rem;margin:0 0 .3rem}
.demo p{color:#94a3b8;font-size:.85rem;margin:.2rem 0 .8rem}
textarea{width:100%;min-height:80px;padding:.7rem .85rem;background:#020617;border:1px solid #1e293b;
border-radius:10px;color:#e2e8f0;font-family:inherit;font-size:.92rem;resize:vertical}
button{margin-top:.75rem;background:linear-gradient(90deg,#00d4ff,#7c3aed);color:#04121f;font-weight:700;
border:none;padding:.7rem 1.3rem;border-radius:10px;font-size:.92rem;cursor:pointer}
button:disabled{opacity:.55;cursor:default}
#demoOut{margin-top:.9rem}
.cta{background:linear-gradient(180deg,#111827,#0d1424);border:1px solid #1e293b;border-radius:14px;
padding:1.2rem;margin:1.6rem 0}
.cta h2{font-size:1.05rem;margin:0 0 .5rem}
.cta .row{margin:.55rem 0}
.cta a.big{display:inline-block;background:linear-gradient(90deg,#00d4ff,#7c3aed);color:#04121f;
font-weight:700;padding:.6rem 1.1rem;border-radius:10px;font-size:.9rem}
code{font-family:ui-monospace,Menlo,monospace;background:#020617;border:1px solid #1e293b;border-radius:8px;
padding:.55rem .7rem;display:block;color:#7fe7ff;font-size:.8rem;word-break:break-all;margin-top:.3rem}
.foot{color:#475569;font-size:.75rem;margin-top:2rem;text-align:center}
.price{color:#4ade80;font-weight:600}
"""

_DEMO_JS = """
async function tryDemo(){
  var q=document.getElementById('q').value.trim();
  var out=document.getElementById('demoOut');
  var btn=document.getElementById('demoBtn');
  if(!q){out.innerHTML='';return;}
  btn.disabled=true;btn.textContent='Asking the models…';out.innerHTML='';
  try{
    var r=await fetch('/o/api/demo',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:q})});
    var d=await r.json();
    if(d && (d.status==='demo_unavailable')){
      out.innerHTML="<div class='card'><div class='resp'>Free live demo is at capacity right now. "+
        "Grab your own free key (10M+ tokens, no card) to keep going:</div>"+
        "<div class='row' style='margin-top:.6rem'><a class='big' href='"+d.signup_url+"'>Get a free Gonka key</a></div></div>";
    } else if(d && d.opinions){
      var h='';
      for(var i=0;i<d.opinions.length;i++){var o=d.opinions[i];
        var body=o.response?o.response:(o.error||o.note||'');
        h+="<div class='card'><div class='who'><span class='badge'>"+esc(o.model||'model')+"</span>"+
          (o.perspective?"<span class='persp'>"+esc(o.perspective)+"</span>":"")+"</div>"+
          "<div class='resp"+(o.response?'':' err')+"'>"+esc(body)+"</div></div>";
      }
      if(d.trial_exhausted||d.status==='ok_trial_exhausted'){
        h+="<div class='row' style='margin-top:.6rem'><a class='big' href='"+
           (d.trial_exhausted&&d.trial_exhausted.signup_url||'"""+AGENT_REFERRAL_URL+"""')+"'>Get your own free key →</a></div>";
      }
      out.innerHTML=h;
    } else {
      out.innerHTML="<div class='card'><div class='resp err'>"+esc((d&&(d.error||d.message))||'Something went wrong.')+"</div></div>";
    }
  }catch(e){out.innerHTML="<div class='card'><div class='resp err'>Network error.</div></div>";}
  btn.disabled=false;btn.textContent='Get a second opinion';
}
function esc(s){s=String(s==null?'':s);return s.replace(/[&<>\"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
"""


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=True)


def _cards(opinions: list) -> str:
    out = []
    for o in (opinions or []):
        body = o.get("response") or o.get("error") or o.get("note") or ""
        is_err = not o.get("response")
        persp = f"<span class='persp'>{_esc(o.get('perspective'))}</span>" if o.get("perspective") else ""
        out.append(
            "<div class='card'><div class='who'>"
            f"<span class='badge'>{_esc(o.get('model') or 'model')}</span>{persp}</div>"
            f"<div class='resp{' err' if is_err else ''}'>{_esc(body)}</div></div>"
        )
    return "".join(out)


def render_page(rec: dict, social: int = 0) -> str:
    prompt = rec.get("prompt") or ""
    opinions = rec.get("opinions") or []
    n = len(opinions)
    title_txt = (prompt[:90] + "…") if len(prompt) > 90 else prompt
    og_title = _esc(f"{title_txt}") or "Second opinion from Gonka AI models"
    og_desc = _esc(
        f"{n} Gonka AI models answered this — see where they agree and differ, "
        f"then ask your own for free."
    )
    social_html = (
        f"<div class='meta'>🔥 {social} second opinions shared today · "
        f"<span class='price'>~$0.000006</span> per question on Gonka</div>"
        if social > 0 else
        f"<div class='meta'><span class='price'>~$0.000006</span> per question on Gonka</div>"
    )
    setup_cmd = "JOINGONKA_API_KEY=&lt;your-key&gt; npx @joingonka/setup"

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex,nofollow'>"
        f"<title>{og_title} · Gonka second opinion</title>"
        "<meta property='og:type' content='website'>"
        f"<meta property='og:title' content='{og_title}'>"
        f"<meta property='og:description' content='{og_desc}'>"
        "<meta property='og:site_name' content='Gonka — Minority Report'>"
        "<meta name='twitter:card' content='summary'>"
        f"<meta name='twitter:title' content='{og_title}'>"
        f"<meta name='twitter:description' content='{og_desc}'>"
        f"<style>{_CSS}</style></head><body>"
        "<div class='brand'><b>Gonka</b> · Minority Report — multi-model second opinion</div>"
        f"<h1>{_esc(prompt)}</h1>"
        f"{social_html}"
        f"{_cards(opinions)}"
        # live demo
        "<div class='demo'><h2>Try your own question — free, no signup</h2>"
        "<p>Ask anything. Every live Gonka model answers in parallel, so you see where they agree "
        "and differ. Runs on the free trial pool.</p>"
        "<textarea id='q' placeholder='e.g. Postgres or MongoDB for time-series analytics?'></textarea>"
        "<button id='demoBtn' onclick='tryDemo()'>Get a second opinion</button>"
        "<div id='demoOut'></div></div>"
        # CTA
        "<div class='cta'><h2>Want this inside your own coding agent?</h2>"
        "<div class='row'>Run multi-model second opinions on <b>your</b> code, in your IDE, without "
        "copy-paste — via the Gonka MCP server.</div>"
        f"<div class='row'><a class='big' href='{AGENT_REFERRAL_URL}'>Get a free Gonka key "
        "(10M+ tokens, no card)</a></div>"
        "<div class='row' style='margin-top:.8rem;color:#94a3b8;font-size:.85rem'>One-command setup "
        "for Claude / Cursor / VS Code:</div>"
        f"<code>{setup_cmd}</code></div>"
        "<div class='foot'>Shared via an unlisted link · not indexed · "
        "<a href='https://gogonka.com/second-opinion'>What is this?</a></div>"
        f"<script>{_DEMO_JS}</script>"
        "</body></html>"
    )


def render_not_found() -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex'>"
        f"<title>Not found · Gonka</title><style>{_CSS}</style></head><body>"
        "<div class='brand'><b>Gonka</b> · Minority Report</div>"
        "<h1>This shared second opinion doesn't exist or has expired.</h1>"
        "<div class='cta'><h2>Get your own — free</h2>"
        f"<div class='row'><a class='big' href='{AGENT_REFERRAL_URL}'>Get a free Gonka key</a></div>"
        "</div></body></html>"
    )
