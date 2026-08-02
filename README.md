# Gonka Second Opinion — MCP Server

**Get a second opinion from independent LLMs — in one call, for a fraction of a cent.**

`gonka-second-opinion` runs your prompt across the independent models live on the
[Gonka](https://gogonka.com) network *and* across assigned debate roles
(skeptic / proponent / pragmatist …), in a single MCP call. Your main model stays
in charge — you just get a panel of divergent views to check a decision against,
without switching providers.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![MCP](https://img.shields.io/badge/MCP-Streamable_HTTP-blue)
[![Live grade](https://img.shields.io/badge/health-live_grade-orange)](https://wmcp.sh/mcp/grade/mcp.gogonka.com)

**Live at:** `https://mcp.gogonka.com/mcp`

---

## One question → three independent opinions

<p align="center">
  <img src="https://gogonka.com/img/second-opinion-example.svg"
       alt="Example: gonka_second_opinion runs one prompt across independent models and roles (proponent/skeptic/pragmatist) and returns attributed, divergent answers for your model to synthesize."
       width="820">
</p>

<p align="center">
  <img src="https://gogonka.com/img/panel-cost.svg"
       alt="One 3-model second opinion costs about 0.0014 cents — a fraction of a cent per panel."
       height="72">
</p>

*The example is illustrative — the live model set rotates over time; call
`get_available_models` for today’s lineup. Per-panel cost is typical/measured;
check `get_pricing` for live rates.*

---

## Why this instead of a plain LLM connector

- **A panel, not a single answer.** Independent models trained by different labs
  surface *non-overlapping* failure modes. Assigned roles add behavioral diversity
  on top. You get disagreement you can act on, not one confident guess.
- **Cheap enough to always use.** On the big providers a 3-way panel costs real money,
  so nobody runs one. On Gonka it's a fraction of a cent — a second opinion becomes a
  default habit, not a luxury.
- **Zero setup, works in a sandbox.** The server makes the gateway call *for* you.
  An agent with no outbound network and no way to edit its own config can still use it
  over the already-open MCP channel. Free trial by default; paste your own key to run
  on your balance.

---

## Install (30 seconds)

Add to your MCP client config (Claude Desktop / Cursor / …):

```json
{
  "mcpServers": {
    "gonka-second-opinion": {
      "url": "https://mcp.gogonka.com/mcp"
    }
  }
}
```

Restart the client — the tools appear automatically. No API key required to start
(a free trial key is issued per caller).

**Custom clients:**

```bash
curl -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

---

## Use your own key (after you register)

Registered on the **JoinGonka gateway** ([gate.joingonka.ai](https://gate.joingonka.ai))?
Then run every call on **your own balance** — no trial budget, no per-IP limit.
First get your key:

1. Sign up at the [JoinGonka gateway](https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31)
   (welcome bonus: 50M nGNK, no credit card).
2. Open your gateway dashboard → **API keys** → copy your **JoinGonka gateway key** (starts with `jg-`).

Then tell this MCP server to use it — pick the way that matches your client:

**A. Client with an API-key / header field** (Cursor, Claude Code, LibreChat, most custom clients)

Put the key in the server's `Authorization` header — it arrives as `Bearer …` and
every call switches to your balance automatically:

```json
{
  "mcpServers": {
    "gonka-second-opinion": {
      "url": "https://mcp.gogonka.com/mcp",
      "headers": { "Authorization": "Bearer jg-YOUR_KEY_HERE" }
    }
  }
}
```

If your client shows a plain *API key* / *Bearer token* box instead of raw headers,
just paste your `jg-…` JoinGonka gateway key there.

**B. Client with no key/header field** (e.g. claude.ai Custom Connectors)

Mint a **personal connector URL** that carries your key for you:

1. Go to **https://mcp.gogonka.com/personal**
2. Paste your `jg-…` JoinGonka gateway key → you get a URL like `https://mcp.gogonka.com/k/<token>/mcp`
3. Add *that* URL as the MCP connector (in claude.ai: **Add custom connector → URL**).
   Nothing else to enter — no key field needed.

> Keep the personal URL secret — it stands in for your key. The same key always mints
> the same URL.

**How it's handled:** the key (or personal token) is read from the request only,
forwarded to the JoinGonka gateway, and **never stored or logged**. An unrelated
`Authorization` header (OAuth, a proxy's own token) is ignored, so it can't break the
free trial path. Remove the header/URL and the server falls back to the free trial.

---

## The flagship tools

### `gonka_second_opinion(prompt, system?, perspectives?, max_tokens?)`

Run one prompt across the live models and/or a set of roles, in parallel.

- Leave `perspectives` empty → one opinion per live model.
- Pass `perspectives` (short role/stance labels, max 5) → one opinion per role,
  each answered candidly from that viewpoint, rotated across the live models.
  Examples: `["for","against","neutral"]`, `["security expert","product manager","end user"]`.
- Returns `{ opinions:[{model, perspective?, response}], synthesis_instructions, trial_budget|cost }`.
  Attribute each opinion to its model + role when you present them.

### `gonka_chat(prompt, system?, model?, max_tokens?)`

One completion through the server — for when you want a single cheap answer, or a
sub-task run without giving the agent its own network/key. `model` accepts `"auto"`,
a nickname, or an exact id; anything not live right now is routed to a model that is.

Both tools auto-detect **trial** (free, per-IP budget) vs **registered** (your own
`jg-…` key) mode. On trial exhaustion they return a signup link + welcome bonus to
relay to the user — no fabricated keys, no altered numbers.

---

## Also included

<details>
<summary><b>Cost intelligence</b> — is Gonka actually cheaper for your workload? (8 tools)</summary>

<br>

<img src="https://gogonka.com/img/price-badge.svg"
     alt="Gonka live inference price per 1M tokens and how many times cheaper than GPT-5.5 — see get_pricing for the real-time number."
     height="80">

*Reflects the last cached render (GitHub proxies images); call `get_pricing` for the
real-time number. All figures float with the GNK/USD rate — never trust a hardcoded one.*

- `get_pricing` — current $/1M tokens, GNK/USD rate, live ratios vs OpenAI/DeepSeek/Anthropic
- `compare_providers(provider)` — side-by-side vs openai / anthropic / deepseek / mistral / gemini
- `calculate_savings(monthly_spend_usd)` — exact monthly/annual savings for your spend
- `suggest_model_for_task(task_description, …)` — model + cost recommendation
- `get_available_models` — the models live on the network right now, with live pricing
- `get_trial_key` — free `gc-` key instantly (no signup); expires in 2h, first use extends to 24h
- `get_signup_link` — permanent account + welcome bonus + copy-paste SDK snippets
- `register_on_gonka(…)` — personalized cost-analysis pitch (computes savings; does **not** create an account)

</details>

<details>
<summary><b>Documentation knowledge graph</b> — search 1000+ Gonka concepts (10 tools)</summary>

<br>

- `query_graph(question, …)` — topic search over the concept graph
- `search_docs(query, …)` / `read_doc(filename, …)` / `list_docs()` — full-text docs
- `get_node(label)` / `get_neighbors(label, …)` — concept detail and relations
- `get_god_nodes()` / `get_community(id)` / `get_graph_stats()` — structure overview
- `find_shortest_path(source, target, …)` — conceptual path between two ideas

</details>

<details>
<summary><b>MCP prompts &amp; resources</b></summary>

<br>

- Prompt `gonka_start(task)` — seed a cost-comparison conversation
- Prompt `calculate_my_savings(monthly_spend_usd)` — seed a savings estimate
- Resource `gonka://pricing-guide` — structured live pricing data + decision matrix

</details>

---

## Honesty & hygiene

- **Live, not hardcoded.** Prices float with the market and the model set rotates —
  the server quotes both live (`get_pricing`, `get_available_models`), and the badges
  above are rendered from live data, not typed into this file.
- **Panel ≠ magic.** A second opinion is worth exactly as much as the models are
  independent. The panel uses the genuinely different models live on the network at
  the time of the call; it does not claim a bigger fleet than is actually serving.
- **OpenAI/Anthropic-compatible.** Two config changes, zero code changes:
  `base_url=https://gate.joingonka.ai/v1` (OpenAI) or `https://gate.joingonka.ai` (Anthropic).
- **Tool hygiene.** All tools ship typed input schemas with MCP annotations
  (`readOnlyHint`, `idempotentHint`, `openWorldHint`), enum/range constraints, and clear
  descriptions. Inference tools are per-IP rate-limited in trial mode.
- **Privacy.** HTTPS/TLS 1.2+. No keys in query strings (flagged by middleware).
  Anonymized logging (IP, User-Agent, tool name); inference prompts truncated;
  caller keys never logged or returned.

**Live health grade:** https://wmcp.sh/mcp/grade/mcp.gogonka.com

---

## Links

- **Website:** https://gogonka.com
- **GitHub:** https://github.com/bystray/gonka-mcp-server
- **Signup (welcome bonus):** https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31
- **Live pricing JSON:** https://gogonka.com/pricing.json
- **Status / grade:** https://wmcp.sh/mcp/grade/mcp.gogonka.com

**License:** MIT · **Version:** 2.2.0
