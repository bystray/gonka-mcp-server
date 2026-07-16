# Gonka Network MCP Server — Technical Specification

**Version of this document:** 1.0 (2026-07-16, reflects commit `7d7a3be`)
**Live endpoint:** `https://mcp.gogonka.com/mcp`
**Status:** production, running as `gonka-mcp.service`

This document is the authoritative description of what the server exposes,
how it behaves, and what it depends on. For the quality audit that shaped the
current behavior see [AUDIT-2026-07-16.md](./AUDIT-2026-07-16.md); for the
regression eval see [evals/gonka_mcp_eval.xml](./evals/gonka_mcp_eval.xml).

---

## 1. Purpose

Public, unauthenticated MCP server with two functions:

1. **Cost intelligence** — live Gonka Network pricing, comparisons against
   OpenAI/Anthropic/DeepSeek/Mistral/Gemini, savings calculators, signup
   referral link, free trial keys for agents that need inference immediately.
2. **Documentation access** — search and exploration of the full Gonka
   Network documentation corpus via a knowledge graph with full-text
   fallback.

Target caller is an **LLM agent** (Claude, GPT, or any MCP client), not a
human. All descriptions, error messages, and response fields are written to
be actionable for a model choosing its next tool call.

## 2. Protocol & Transport

| Property | Value |
|---|---|
| Protocol | MCP (Model Context Protocol), JSON-RPC 2.0 |
| Transport | Streamable HTTP, **stateless** (`stateless_http=True`) |
| Response mode | plain JSON (`json_response=True`), no SSE streaming required |
| Framework | FastMCP (Python), `serverInfo.name = "Gonka Network Pricing"` |
| Authentication | **none** — public server; never send api_key/credentials in query params (middleware logs such attempts) |
| Session state | none; every request is independent, safe behind load balancers |

`serverInfo.version` reported on `initialize` is the FastMCP library version,
not the product version. Product version lives in the catalog manifests
(`mcp.json`, `server.json`) — currently `2.0.0`.

## 3. Deployment & Infrastructure

```
Internet ──HTTPS──> nginx (mcp.gogonka.com, :443, Let's Encrypt)
                      └─ proxy_pass → 127.0.0.1:8643 (uvicorn, localhost-only)
                            └─ systemd: gonka-mcp.service
                                 User=agentgonka
                                 WorkingDirectory=/opt/agentgonka/gonka-mcp
                                 ExecStart=/opt/agentgonka/venv/bin/python server.py
                                 Restart=on-failure (5s)
                                 Hardening: NoNewPrivileges, PrivateTmp,
                                            ProtectSystem=strict,
                                            ReadWritePaths=/opt/agentgonka,
                                            ReadOnlyPaths=/var/www/gogonka
```

- **Deploy procedure:** edit files → `systemctl restart gonka-mcp` (no build step).
- **Env** (`.env`, systemd `EnvironmentFile`): Langfuse credentials
  (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`,
  `OTEL_SERVICE_NAME`). Missing Langfuse keys must never prevent startup
  (guarded import).
- **Client IP** is taken from `X-Real-IP` (set by nginx), falling back to the
  first entry of `X-Forwarded-For`.

## 4. Data Sources (all reads are per-request; no restart needed on refresh)

| Source | Path / URL | Refresh | Used by |
|---|---|---|---|
| Pricing snapshot | `/var/www/gogonka/pricing.json` | systemd timer, every 10 min (GNK/USD from DEX api.hot-labs.org + competitor rates) | all pricing tools, instructions, resource |
| Gateway directory | `/var/www/gogonka/gateways_status.json` | external monitor | `get_pricing.gateways` |
| Live model list | `GET https://gate.joingonka.ai/v1/models` | on demand, 300 s in-process cache; fetch failure ⇒ "unknown, don't filter" (stale cache > nothing) | `get_available_models.status` |
| Documentation graph | `/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json` (override: env `GONKA_WIKI_GRAPH`) | cron re-scrape; hot-reloaded on mtime/size change, thread-safe | all `*_graph`/node tools |
| Documentation files | `*.md` under `/opt/agentgonka/gonka-wiki/content-split/` (recursive; `graphify-out/`, `assets/`, dotdirs excluded) | same cron | `read_doc`, `list_docs`, `search_docs`, `query_graph` fallback |
| Trial key store | Postgres `a2a_agent.agent_trial_keys` (docker `a2a_gonka_db`, localhost:5432) | live | `get_trial_key` idempotency check |
| Trial key issuer | `POST http://127.0.0.1:8646/agent/trial` (inferGONKA a2a service, docker). **Must stay localhost** — the public domain hairpins through nginx which overwrites `X-Real-IP` with the server's own egress IP | live | `get_trial_key` creation |

## 5. Middleware (execution order)

1. **SecurityMiddleware** — logs a warning if `api_key`/`apikey`/`api-key`
   appears in the query string (public server, credentials don't belong there).
2. **StatsMiddleware** — appends one JSON line per message to
   `/opt/agentgonka/mcp-stats.jsonl`: `ts, ip, ua, tool, ms` (+
   `client_name`/`client_version` on `initialize`). On `initialize` it also
   rebuilds server instructions so new sessions see current pricing. Logging
   failures never break request handling.
3. **LangfuseMiddleware** — traces every `tools/call` as a span (tool name,
   args, ip/ua, result excerpt). Detects both hard failures (`isError=true`)
   and soft failures (tool returned `{"error": ...}` with HTTP 200) and marks
   the span level ERROR accordingly.

## 6. Tools

18 tools in three groups. All pricing tools return JSON objects; all docs
tools return plain text. Every tool carries MCP annotations
(`readOnlyHint`, `idempotentHint`, `openWorldHint`, `title`); the only
non-read-only tool is `get_trial_key`.

### 6.1 Pricing & conversion group

| Tool | Params (→ default) | Returns |
|---|---|---|
| `get_pricing` | — | Live price snapshot: `usd_per_1m_tokens`, `gnk_usd_price` + source, ratios vs OpenAI/DeepSeek, `deposit_50_usd_tokens`, full `gateways[]` directory (name, status, USD/1M, models, SDK support, bonus, latency), `signup_url`, `welcome_bonus`, `data_last_updated` |
| `get_available_models` | — | `models[]` with `id` (usable directly in `chat.completions.create`), `status` (checked against the **live** gateway `/models` — a model listed in pricing.json but not served right now is reported `unavailable`), `usd_per_1m_tokens` |
| `compare_providers` | `provider: enum(openai,anthropic,deepseek,mistral,gemini)` → openai | Side-by-side cost per 1M tokens, live ratio, `savings_examples[]` for $10/$100/$1000 budgets, SDK migration snippets |
| `calculate_savings` | `monthly_spend_usd: number` → 100 | Monthly/annual savings, `cost_ratio`, tokens-per-budget at both providers, deposit-fee note. Input guards: rejects ≤ 0 and > 1 000 000 with `{"error": ...}` |
| `suggest_model_for_task` | `task_description: str` (required), `monthly_budget_usd` → 0, `current_provider: enum` → openai | Recommended model + reason, all available models, migration steps, savings if budget given. *Known limitation: recommendation is currently static (always the cheapest general model) — see AUDIT P3* |
| `get_signup_link` | — | `signup_url` (referral), verified welcome-bonus info, quick-start snippets (Python/Node/env/Anthropic SDK), `available_models[]`, referral program terms (L1 10% / L2 3% of deposit fee) |
| `register_on_gonka` | `monthly_spend_usd` → 100, `current_provider: str` → openai, `user_query: str` → "" | Personalized cost analysis + signup URL. **Does NOT create an account** — the description states this explicitly; the caller completes registration at `signup_url` |

### 6.2 Trial key

`get_trial_key()` — no parameters. Issues (or re-returns) a free
OpenAI-compatible key.

Contract:

| Field | Meaning |
|---|---|
| `status` | `issued` \| `existing` \| `waitlisted` \| `error` |
| `api_key` | `gc-…` key (issued/existing) |
| `base_url` | `https://gate.joingonka.ai/v1` |
| `tokens_limit` | 100 000 tokens |
| `rate_limit_rpm` | 10 |
| `expires_at` | ISO-8601 UTC |
| `ttl_note` | key expires **2 h unused**; first inference call auto-extends to 24 h |
| `recommended_model` | model id to put in the first request (both branches) |
| `available_models` / `fallback_models` | models with strengths; retry order on `model_unavailable` (issued branch) |
| `fallback_guidance` | what to do when the recommended model errors |
| `when_limit_reached` | `{error_to_catch: "child_key_limit_exceeded", signup_url}` — the conversion hand-off (both branches) |
| `quick_start` | ready-to-run Python snippet incl. model id (both branches) |

Flow:

```
get_trial_key
  ├─ ip = X-Real-IP
  ├─ SELECT agent_trial_keys WHERE client_ip=ip AND is_active AND not expired (24h window)
  │    └─ hit  → status=existing (idempotent: one key per IP per 24 h)
  └─ miss → POST 127.0.0.1:8646/agent/trial  (inferGONKA creates gateway child key + DB row)
       ├─ success    → status=issued (full contract above)
       ├─ waitlisted → queue_position, retry_after_seconds, signup_url
       └─ exception  → status=error with human-readable message
                       ("temporarily unavailable, retry in ~60 s or register"),
                       raw exception preserved in `detail`, signup_url included
```

### 6.3 Documentation group (knowledge graph + full text)

All read-only, all return plain text. Every "not found" answer names the
next tool to try instead of dead-ending.

| Tool | Params (→ default) | Behavior |
|---|---|---|
| `query_graph` | `question` (required), `depth` → 3 (max 6), `token_budget` → 2000 | **Primary entry point.** Scores graph nodes (IDF, exact/prefix/substring), BFS from top seeds, renders NODE/EDGE lines within budget. Relevance gate: the longest specific term must appear as a whole word in seed labels, ≥ 60 % of specific terms must hit — otherwise falls through to full-text search over all `.md` files (densest-window excerpts, nav-block skipping, canonical files ranked above `gonka-docs-full_partN` dumps) |
| `search_docs` | `query` (required), `max_results` → 3, `context_chars` → 400 | Full-text **AND search over whitespace-split words** (case-insensitive; a file must contain every word somewhere). Excerpt anchored on the rarest word. Zero hits ⇒ suggests fewer keywords or `query_graph` |
| `read_doc` | `filename` (required, exact or partial `.md` name), `max_chars` → 8000 | Full file content, truncated at `max_chars`. Fuzzy fallback on partial names. *Known limitation: scraped pages carry ~2.5–3 KB of site-navigation boilerplate at the top — raise `max_chars` for content-heavy files (AUDIT P3)* |
| `list_docs` | — | All `.md` filenames, sorted |
| `get_node` | `label` (required, concept name/substring) | Node details: label, id, source file+location, community, degree |
| `get_neighbors` | `label` (required), `relation_filter` → "" | In/out edges with relation + confidence |
| `get_community` | `community_id: int` (required) | All concepts in one detected cluster |
| `get_god_nodes` | `top_n` → 10 | Most-connected concepts — orientation when you don't know where to start |
| `get_graph_stats` | — | Node/edge/community counts, confidence distribution |
| `find_shortest_path` | `source`, `target` (required), `max_hops` → 8 | Concept-to-concept path over the undirected view; refuses paths longer than `max_hops` |

Current graph size (2026-07-16): 2 712 nodes, 2 675 edges, 215 communities,
96 % EXTRACTED edges.

## 7. Prompts & Resources

| Kind | Name | Purpose |
|---|---|---|
| prompt | `gonka_start(task)` | Seeds a cost-comparison conversation with live ratio/price |
| prompt | `calculate_my_savings(monthly_spend_usd)` | Seeds a savings-estimate conversation |
| resource | `gonka://pricing-guide` | Markdown snapshot for agent decision-making: live prices, competitor table, decision matrix, deposit example, integration snippet, suggested tool sequences. Rebuilt from `pricing.json` on every read |

## 8. Server Instructions

Rebuilt on every `initialize` from live pricing data. Neutral, English-only:
what Gonka is, current price/ratios, the two-line SDK integration, a tool
guide, and the no-credentials-in-query-params rule. (The pre-2026-07-16
"call tools automatically when the user mentions billing" trigger style was
removed deliberately — see AUDIT finding B4.)

## 9. Error-Handling Conventions

- **Validation errors** (bad enum, wrong type): rejected by Pydantic before
  the tool body runs → MCP `isError=true`.
- **Soft failures** (tool ran, upstream/input problem): HTTP 200 with
  `{"error": "..."}` (pricing group) or an explanatory string (docs group).
  Every such message must state *what to do next* (which tool to call, when
  to retry, where to sign up). Langfuse middleware surfaces both kinds as
  ERROR spans.
- **Upstream trial-service outage**: `status=error` with retry guidance;
  raw exception only in `detail`.

## 10. Observability

| Channel | What |
|---|---|
| `/opt/agentgonka/mcp-stats.jsonl` | one line per MCP message: ts, ip, ua, tool, ms (basis for `gogonka.com/mcp-dashboard/`, regenerated every minute by `gen_data.py`; honest-layer bot filtering documented there) |
| Langfuse | per-tool-call spans with args, caller, result, error status |
| `journalctl -u gonka-mcp` | HTTP access log + startup/shutdown |

## 11. Catalog Manifests

| File | Consumer | Notes |
|---|---|---|
| `mcp.json` | generic MCP catalogs | ⚠ lists only 5 of 18 tools; version 2.0.0 |
| `server.json` | MCP official registry schema (2025-12-11) | `io.github.bystray/gonka-mcp-server`; fuller tool list |
| `smithery.yaml` | Smithery | HTTP endpoint config |
| `.well-known/` | discovery | served by nginx |

⚠ **Known drift** (not yet fixed, tracked for next release): manifests and
README quote stale ratios ("6 800–7 681×" vs live ~13 500×), README's welcome
bonus note ("~11 000 tokens") contradicts live data (~10.8 M tokens), and
`mcp.json.tools` omits the docs group and trial key entirely.

## 12. Testing & Regression

- `test_mcp.py` — legacy smoke test of the HTTP endpoint.
- `evals/gonka_mcp_eval.xml` — 10 verified Q&A pairs (mcp-builder Phase 4
  format). Run after any change to tool names/descriptions/schemas; every
  answer must be reachable by an agent holding only this server's tools.
- Manual protocol check: `initialize` → `tools/list` → targeted `tools/call`
  against `127.0.0.1:8643/mcp` (see AUDIT for the verification transcript).

## 13. Deferred / Known Limitations (AUDIT P3)

1. No `gonka_` prefix on tool names; several generic names (`query_graph`,
   `get_node`, …) rely on descriptions for disambiguation in multi-server
   agents. Renaming is a breaking change for connected catalogs — planned as
   a single coordinated release.
2. Tool-surface consolidation (18 → ~11): `search_docs` overlaps
   `query_graph`'s fallback; `compare_providers`/`calculate_savings`/
   `register_on_gonka` share the same math; graph-introspection tools
   (`get_community`, `get_god_nodes`, `get_graph_stats`) have little external
   value.
3. `suggest_model_for_task` does not actually route by task.
4. `read_doc` returns scraped-page navigation boilerplate; corpus contains 72
   `gonka-docs-full_partN.md` dump files that pollute `list_docs`; the graph
   has duplicate/multilingual node artifacts.
5. Manifest drift (see §11).
