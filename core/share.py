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
DEMO_MAX_TOKENS     = int(os.environ.get("DEMO_MAX_TOKENS", "700"))
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
def save_opinion(prompt: str, opinions: list, cost: dict | None = None,
                 synthesis: str = "", shared_via: str = "") -> dict:
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
        if o.get("model_id"):
            c["model_id"] = o["model_id"]          # full id with version (page shows this)
        if o.get("perspective"):
            c["perspective"] = o["perspective"]
        if o.get("response") is not None:
            c["response"] = _sanitize(_redact(o.get("response") or ""))
        if o.get("truncated"):
            c["truncated"] = True
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
        "agreement": _agreement(safe_opinions),    # deterministic, always computed
        "cost": cost or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if synthesis and synthesis.strip():
        record["synthesis"] = _sanitize(_redact(synthesis.strip()))[:4000]
        if shared_via:
            record["shared_via"] = shared_via[:60]
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
.grid{display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin:.4rem 0 1rem}
@media(max-width:640px){.grid{grid-template-columns:1fr}}
.card{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:1rem 1.15rem}
.card .who{display:flex;align-items:center;gap:.5rem;margin-bottom:.15rem}
.badge{background:rgba(0,212,255,.1);border:1px solid rgba(0,212,255,.25);color:#7fe7ff;
font-size:.72rem;font-weight:700;padding:.16em .6em;border-radius:999px}
.persp{color:#a78bfa;font-size:.8rem}
.mid{display:block;color:#556074;font-size:.68rem;font-family:ui-monospace,Menlo,monospace;margin-bottom:.5rem}
.resp{color:#cbd5e1;font-size:.95rem;word-wrap:break-word}
.resp.err{color:#f87171}
.trunc{margin-top:.5rem;font-size:.78rem;color:#94a3b8;font-style:italic;border-top:1px dashed #1e293b;padding-top:.4rem}
.resp strong{color:#e2e8f0}
.resp .mdh{font-weight:700;color:#e2e8f0;font-size:1em;margin:.5rem 0 .25rem}
.resp code.inl{background:rgba(0,212,255,.08);border:1px solid rgba(0,212,255,.18);border-radius:5px;
padding:.05em .35em;font-family:ui-monospace,Menlo,monospace;font-size:.85em;color:#7fe7ff}
.resp pre{background:#020617;border:1px solid #1e293b;border-radius:8px;padding:.6rem .7rem;overflow-x:auto;margin:.5rem 0}
.resp pre code{color:#9fe;font-family:ui-monospace,Menlo,monospace;font-size:.82em}
.resp ul{margin:.4rem 0;padding-left:1.1rem}
.agree{display:flex;align-items:center;gap:.55rem;border-radius:10px;padding:.6rem .85rem;margin:.2rem 0 .4rem;
font-size:.9rem;font-weight:600}
.agree.high{background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.3);color:#86efac}
.agree.mixed{background:rgba(250,204,21,.08);border:1px solid rgba(250,204,21,.28);color:#fde68a}
.agree.low{background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.28);color:#fca5a5}
.agree .hint{font-weight:400;font-size:.74rem;color:#94a3b8}
.verdict{background:#0d1424;border:1px solid rgba(167,139,250,.3);border-radius:12px;padding:.9rem 1.1rem;margin:.2rem 0 1rem}
.verdict .lbl{color:#a78bfa;font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.verdict .body{color:#e2e8f0;font-size:.95rem;margin-top:.3rem}
.sub{color:#64748b;font-size:.85rem;margin:.2rem 0 1rem}
.intro{background:linear-gradient(180deg,#101a30,#0b1220);border:1px solid rgba(0,212,255,.22);
border-radius:14px;padding:1rem 1.15rem;margin:.2rem 0 1.3rem}
.intro .it{font-size:1.05rem;font-weight:700;color:#e2e8f0;margin-bottom:.35rem}
.intro .ib{font-size:.9rem;color:#94a3b8;line-height:1.55}
.intro .ip{font-size:.78rem;color:#4ade80;margin-top:.5rem}
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
  btn.disabled=true;btn.textContent=btn.dataset.busy||'…';out.innerHTML='';
  try{
    var r=await fetch('/o/api/demo',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:q})});
    var d=await r.json();
    if(d && (d.status==='demo_unavailable')){
      out.innerHTML="<div class='card'><div class='resp'>Free live demo is at capacity right now. "+
        "Grab your own free key (10M+ tokens, no card) to keep going:</div>"+
        "<div class='row' style='margin-top:.6rem'><a class='big' href='"+d.signup_url+"'>Get a free Gonka key</a></div></div>";
    } else if(d && d.opinions){
      var h="<div class='grid'>";
      for(var i=0;i<d.opinions.length;i++){var o=d.opinions[i];
        var body=o.response?o.response:(o.error||o.note||'');
        var full=o.model_id&&o.model_id!==o.model?"<span class='mid'>"+esc(o.model_id)+"</span>":"";
        h+="<div class='card'><div class='who'><span class='badge'>"+esc(o.model||'model')+"</span>"+
          (o.perspective?"<span class='persp'>"+esc(o.perspective)+"</span>":"")+"</div>"+full+
          "<div class='resp"+(o.response?'':' err')+"'>"+(o.response?mdLite(body):esc(body))+"</div></div>";
      }
      h+="</div>";
      if(d.trial_exhausted||d.status==='ok_trial_exhausted'){
        h+="<div class='row' style='margin-top:.6rem'><a class='big' href='"+
           (d.trial_exhausted&&d.trial_exhausted.signup_url||'"""+AGENT_REFERRAL_URL+"""')+"'>Get your own free key →</a></div>";
      }
      out.innerHTML=h;
    } else {
      out.innerHTML="<div class='card'><div class='resp err'>"+esc((d&&(d.error||d.message))||'Something went wrong.')+"</div></div>";
    }
  }catch(e){out.innerHTML="<div class='card'><div class='resp err'>Network error.</div></div>";}
  btn.disabled=false;btn.textContent=btn.dataset.idle||'Get a second opinion';
}
function esc(s){s=String(s==null?'':s);return s.replace(/[&<>\"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function mdLite(s){s=esc(String(s==null?'':s)).replace(/<think>[\\s\\S]*?<\\/think>/gi,'').replace(/<think>[\\s\\S]*$/i,'');
  s=s.replace(/```([\\s\\S]*?)```/g,function(m,c){return "<pre><code>"+c.replace(/^\\n+|\\n+$/g,'')+"</code></pre>";});
  s=s.replace(/`([^`\\n]+)`/g,"<code class='inl'>$1</code>").replace(/\\*\\*([^*\\n]+)\\*\\*/g,'<strong>$1</strong>');
  return s.replace(/\\n{2,}/g,'<br><br>').replace(/\\n/g,'<br>');}
"""


def _esc(s: str) -> str:
    return _html.escape(s or "", quote=True)


_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN = re.compile(r"<think>.*$", re.S | re.I)


def _sanitize(text: str) -> str:
    """Strip reasoning-model <think> blocks (and a dangling open <think>) so the
    page shows the actual answer, not internal monologue / a cut-off think."""
    if not text:
        return text or ""
    t = _THINK_RE.sub("", text)
    t = _THINK_OPEN.sub("", t)
    return t.strip()


_WORD_RE = re.compile(r"[a-zа-я0-9]{4,}", re.I)


def _agreement(opinions: list) -> dict | None:
    """Deterministic, no-LLM heuristic of how much the answers overlap in wording.
    HONESTLY a text-similarity signal, not a truth verdict. Returns
    {level: high|mixed|low} or None if <2 answers to compare."""
    texts = [o.get("response") for o in (opinions or []) if o.get("response")]
    if len(texts) < 2:
        return None
    sets = [set(w.lower() for w in _WORD_RE.findall(t)) for t in texts]
    sims, pairs = 0.0, 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            a, b = sets[i], sets[j]
            if a and b:
                sims += len(a & b) / len(a | b)
                pairs += 1
    if not pairs:
        return None
    score = sims / pairs
    level = "high" if score >= 0.32 else ("mixed" if score >= 0.15 else "low")
    return {"level": level, "score": round(score, 3)}


# --- tiny markdown → HTML (stdlib only; input is escaped first, so XSS-safe) ---
def _md(text: str) -> str:
    if not text:
        return ""
    s = _esc(_sanitize(text))
    # fenced code blocks ```...```
    s = re.sub(r"```(?:[a-z0-9]+\n)?(.*?)```",
               lambda m: "<pre><code>" + m.group(1).strip("\n") + "</code></pre>", s, flags=re.S)
    # inline `code`
    s = re.sub(r"`([^`\n]+)`", r"<code class='inl'>\1</code>", s)
    # bold **text**
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", s)
    # bullet lists (lines starting with - or *)
    lines, out, in_ul = s.split("\n"), [], False
    for ln in lines:
        h = re.match(r"\s*(#{1,6})\s+(.*)", ln)
        m = re.match(r"\s*[-*]\s+(.*)", ln)
        if h:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(f"<div class='mdh'>{h.group(2)}</div>")
        elif m:
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append(f"<li>{m.group(1)}</li>")
        else:
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append(ln)
    if in_ul:
        out.append("</ul>")
    s = "\n".join(out)
    # paragraphs / line breaks (leave block tags alone)
    s = re.sub(r"\n{2,}", "<br><br>", s)
    s = re.sub(r"(?<!>)\n(?!<)", "<br>", s)
    return s


def _cards(opinions: list, L: dict) -> str:
    out = []
    for o in (opinions or []):
        persp = f"<span class='persp'>{_esc(o.get('perspective'))}</span>" if o.get("perspective") else ""
        full = o.get("model_id") or ""
        sub = f"<span class='mid'>{_esc(full)}</span>" if full and full != o.get("model") else ""
        if o.get("error"):
            # a real failure (gateway/model unavailable) — this IS an error
            inner = f"<div class='resp err'>{_esc(o['error'])}</div>"
        elif o.get("response"):
            inner = f"<div class='resp'>{_md(o['response'])}</div>"
            if o.get("truncated"):          # cut off at token cap — info, not error
                inner += f"<div class='trunc'>{_esc(L['trunc'])}</div>"
        else:
            # ran but produced no final text (budget spent reasoning) — info, not error
            inner = f"<div class='trunc'>{_esc(L['no_final'])}</div>"
        out.append(
            "<div class='card'><div class='who'>"
            f"<span class='badge'>{_esc(o.get('model') or 'model')}</span>{persp}</div>"
            f"{sub}{inner}</div>"
        )
    return f"<div class='grid'>{''.join(out)}</div>"


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return (s[:n].rsplit(" ", 1)[0] or s[:n]) + "…"


def _lang(s: str) -> str:
    cyr = len(re.findall(r"[а-яё]", s or "", re.I))
    lat = len(re.findall(r"[a-z]", s or "", re.I))
    return "ru" if cyr > lat else "en"


_STR = {
    "ru": {
        "intro_t": "🧠 Второе мнение от нескольких ИИ",
        "intro_b": "Один и тот же вопрос задали <b>нескольким независимым ИИ-моделям сразу</b>. Ниже — их ответы рядом. Где модели сходятся — ответу можно доверять; где расходятся — стоит перепроверить. Дешёвый способ не полагаться на одну модель.",
        "intro_p": "На сети Gonka — ~$0.000006 за вопрос.",
        "sub": "Вопрос задан {n} моделям независимо.",
        "ag_high": "≈ Ответы во многом совпадают", "ag_mixed": "◐ Частичное совпадение",
        "ag_low": "⚠ Ответы заметно расходятся",
        "ag_hint": "— эвристика по тексту, читай оба ответа",
        "trunc": "… ответ обрезан по лимиту токенов (это не ошибка модели)",
        "no_final": "Модель потратила лимит токенов на рассуждения и не успела дать финальный ответ (не ошибка).",
        "verdict_lbl": "Вывод спросившего агента", "via": "поделился через",
        "demo_h": "Задай свой вопрос — бесплатно, без регистрации",
        "demo_p": "Спроси что угодно. Все живые модели Gonka отвечают параллельно — сравни их бок о бок. Работает на бесплатном trial-пуле.",
        "demo_ph": "напр. PostgreSQL или MongoDB для аналитики по времени?",
        "demo_idle": "Получить второе мнение", "demo_busy": "Спрашиваю модели…",
        "cta_h": "Хочешь так же в своём ИИ-агенте?",
        "cta_b": "Запускай мультимодельное второе мнение по <b>своему</b> коду прямо в IDE, без копипаста — через MCP-сервер Gonka.",
        "cta_link": "Получить бесплатный ключ Gonka (10M+ токенов, без карты)",
        "cta_setup": "Установка одной командой для Claude / Cursor / VS Code:",
        "foot_a": "Открыто по секретной ссылке · не индексируется · ", "what": "Что это?",
    },
    "en": {
        "intro_t": "🧠 A second opinion from multiple AIs",
        "intro_b": "The same question was put to <b>several independent AI models at once</b>. Their answers are side by side below. Where they agree, you can trust the answer; where they differ, dig deeper. A cheap way not to rely on a single model.",
        "intro_p": "On the Gonka network — ~$0.000006 per question.",
        "sub": "The question was asked to {n} models independently.",
        "ag_high": "≈ Answers largely overlap", "ag_mixed": "◐ Partial overlap",
        "ag_low": "⚠ Answers differ notably",
        "ag_hint": "— text-similarity heuristic, read both answers",
        "trunc": "… answer cut off at the token limit (not a model error)",
        "no_final": "The model spent its token budget on reasoning and returned no final answer (not an error).",
        "verdict_lbl": "Asking agent's take", "via": "shared via",
        "demo_h": "Try your own question — free, no signup",
        "demo_p": "Ask anything. Every live Gonka model answers in parallel, so you can compare them side by side. Runs on the free trial pool.",
        "demo_ph": "e.g. Postgres or MongoDB for time-series analytics?",
        "demo_idle": "Get a second opinion", "demo_busy": "Asking the models…",
        "cta_h": "Want this inside your own coding agent?",
        "cta_b": "Run multi-model second opinions on <b>your</b> code, in your IDE, without copy-paste — via the Gonka MCP server.",
        "cta_link": "Get a free Gonka key (10M+ tokens, no card)",
        "cta_setup": "One-command setup for Claude / Cursor / VS Code:",
        "foot_a": "Shared via an unlisted link · not indexed · ", "what": "What is this?",
    },
}


def render_page(rec: dict, social: int = 0) -> str:
    prompt = rec.get("prompt") or ""
    opinions = rec.get("opinions") or []
    n = len(opinions)
    L = _STR[_lang(prompt)]
    og_title = _esc(_clip(prompt, 80)) or "Second opinion from Gonka AI models"
    og_desc = _esc(f"A multi-model second opinion — see how {n} independent AI models answered this.")

    # Agent's real synthesis wins. The crude lexical badge is only a FALLBACK when
    # there's no synthesis — otherwise it can visibly contradict the synthesis
    # (different wording ≠ disagreement).
    verdict_html = ""
    if rec.get("synthesis"):
        via = rec.get("shared_via")
        via_html = f" · {L['via']} {_esc(via)}" if via else ""
        verdict_html = (f"<div class='verdict'><div class='lbl'>{L['verdict_lbl']}{via_html}</div>"
                        f"<div class='body'>{_md(rec['synthesis'])}</div></div>")

    agree_html = ""
    ag = rec.get("agreement")
    if not rec.get("synthesis") and ag and ag.get("level") in ("high", "mixed", "low"):
        lbl = L["ag_" + ag["level"]]
        agree_html = (f"<div class='agree {ag['level']}'>{lbl}"
                      f"<span class='hint'>{L['ag_hint']}</span></div>")

    social_html = (
        f"<div class='meta'><span class='price'>~$0.000006</span> · {social} shared today</div>"
        if social > 0 else "")

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
        "<div class='brand'><b>Gonka</b> · Minority Report</div>"
        # intro — what this page IS (the cold-visitor explainer)
        f"<div class='intro'><div class='it'>{L['intro_t']}</div>"
        f"<div class='ib'>{L['intro_b']}</div><div class='ip'>{L['intro_p']}</div></div>"
        f"<h1>{_esc(prompt)}</h1>"
        f"<div class='sub'>{L['sub'].format(n=n)}</div>"
        f"{social_html}"
        f"{agree_html}"
        f"{verdict_html}"
        f"{_cards(opinions, L)}"
        f"<div class='foot'>{L['foot_a']}"
        f"<a href='https://gogonka.com/second-opinion'>{L['what']}</a></div>"
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
