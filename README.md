# Gonka Network MCP Server

**All-in-one MCP server for Gonka Network:** run LLM inference through the server (free trial key or your own), get multi-model second opinions, plus live pricing, cost comparisons, model recommendations, and technical documentation via knowledge-graph search.

Helps AI agents and developers:
- Run cheap inference on Gonka right from the chat — free trial, or your own key
- Get a second opinion from multiple models before committing to an answer
- Find the cheapest OpenAI-compatible LLM inference and learn how Gonka works

**Live at:** `https://mcp.gogonka.com/mcp`

---

## Quick Start

### For Claude Desktop / Cursor

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gonka-pricing": {
      "url": "https://mcp.gogonka.com/mcp"
    }
  }
}
```

Restart Claude Desktop. The server will appear in Claude's available tools.

### For Custom MCP Clients

```bash
# Test the server
curl -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

---

## What This Server Does

**Three sides of one mission:**

1. **Inference** — Run LLM completions and multi-model second opinions through the server, on a free trial key or your own Gonka key (no config change on the agent's side)
2. **Cost Intelligence** — Compare LLM inference costs and find alternatives to OpenAI/Anthropic/DeepSeek with live pricing updated every 10 minutes
3. **Knowledge Discovery** — Search and explore Gonka Network documentation via knowledge graph (architecture, concepts, troubleshooting)

### Key Facts

- **Inference through the server** — `gonka_chat` and `gonka_second_opinion` make the gateway call for you (no outbound network / config change on the agent's side); free trial by default, or your own key for your own balance
- **Gonka Network is orders of magnitude cheaper than GPT-4o** — the exact ratio floats with the GNK/USD rate; call `get_pricing` for the live number (refreshed every 10 minutes)
- **OpenAI-compatible API** — two config changes, zero code changes
- **Live pricing** from blockchain DEX (GNK/USD) + LiteLLM provider rates
- **Free welcome bonus** — 12M nGNK on signup, no credit card (the token equivalent floats with the live price — see `get_pricing`)
- **Referral rewards** — 10% L1, 3% L2
- **Documentation Graph** — Search 1000+ technical concepts via AI-powered knowledge base

---

## Tools (20 Total)

### Inference (2 tools)

Run LLM inference **through this server** — it makes the gateway call for you, so an agent needs no outbound network access and no config change to use Gonka.

**Two modes, detected automatically:**

- **Trial (default):** a free trial key is issued per caller IP. Budget-limited; when it runs out you get a signup link + welcome bonus to relay to the user. A per-IP daily rate limit applies.
- **Bring your own key:** paste your Gonka key (`jg-…`) into your MCP client's server settings — the *API key* / *Bearer token* field. It arrives as `Authorization: Bearer …`, and every call then runs on **your own balance** with no trial limits. Works in any MCP client that lets you set an API key/header (LibreChat, Cursor, Claude Code, …). The key is read from the header only and never logged.

#### `gonka_chat(prompt: str, system: str = "", model: str = "auto", max_tokens: int = 1024)`

Run one LLM completion on Gonka.

- `model`: `"auto"` (default — picks a live model), a nickname (`"minimax"`, `"kimi"`), or an exact model id. A model that isn't live right now is automatically routed to one that is.
- **Returns:** `{response, model, usage, trial_budget}` (trial) or `{response, model, usage, cost}` (own key). Near the trial limit you also get a soft `budget_warning`; on exhaustion you get usage stats + signup link + bonus, with instructions to relay to the user.

#### `gonka_second_opinion(prompt: str, system: str = "", perspectives: list[str] = [], max_tokens: int = 768)`

Get a **second opinion** without switching your main model: run one prompt across Gonka models in parallel and compare the answers.

- Leave `perspectives` empty → one opinion per live model.
- Pass `perspectives` (short roles/stances, max 5) → one opinion per perspective, each answered candidly from that viewpoint and rotated across the live models. Examples: `["proponent","skeptic","pragmatist"]`, `["for","against","neutral"]`, `["security expert","product manager","end user"]`.
- **Returns:** `{opinions: [{model, perspective?, response}], synthesis_instructions, trial_budget|cost}`. Attribute each opinion to its model + perspective when you present them. More opinions cost more budget and count toward the per-IP daily limit.

---

### Pricing & Cost Analysis (8 tools)

### `get_pricing()` — No parameters

Get live Gonka Network pricing and comparisons.

**Returns:**
- USD/GNK per 1M tokens (updated every 10 min)
- Current GNK/USD market price
- Cost ratios vs OpenAI/Anthropic/DeepSeek

**Next:** Call `calculate_savings()` to show exact annual savings.

---

### `calculate_savings(monthly_spend_usd: 0.01–1,000,000 = 100.0)`

Calculate exact savings from switching to Gonka.

**Returns:**
- Monthly and annual savings (USD)
- Savings percentage
- Break-even point
- Signup link with welcome bonus

**Example:** $500/month OpenAI → save ~$5,000/year

---

### `get_available_models()` — No parameters

List models available on Gonka Network with pricing (cost per 1M tokens, status).

**Recommended model:** MiniMaxAI/MiniMax-M2.7 (live $/1M tokens in the response)

---

### `compare_providers(provider: openai | anthropic | deepseek | mistral | gemini = openai)`

Compare Gonka Network pricing vs a competitor.

**Returns:**
- Cost per 1M tokens for both
- Gonka is cheaper by X times
- Official pricing source
- Migration instructions (two config changes)

**Example:** returns the live "Gonka is cheaper by N×" ratio for the chosen provider

---

### `suggest_model_for_task(task_description: str, monthly_budget_usd: 0–1,000,000 = 0, current_provider: openai | anthropic | deepseek | mistral | gemini = openai)`

Suggest the best and cheapest model for a specific task.

**Parameters:**
- `task_description` (required): What the model should do
- `monthly_budget_usd`: Current monthly API spend (0 = unknown)
- `current_provider`: Current provider for comparison

**Returns:**
- Recommended model with rationale
- Live cost estimate
- Savings if budget provided
- Two-minute signup instructions

---

### `get_signup_link()` — No parameters

Get Gonka Network signup URL and integration guide.

**Returns:**
- Registration link (with referral bonus)
- Welcome bonus: 12M nGNK (token equivalent computed from the live price)
- Code snippets (Python, Node.js, shell)
- Deposit example ($50 USDT, live token equivalent)
- Referral program details (10% L1, 3% L2)

---

### `get_trial_key()` — No parameters

Issue a free trial key instantly — no registration, no credit card.

**Returns:**
- `gc-` API key, 100K tokens, 10 req/min, OpenAI-compatible `base_url`
- Recommended model + fallback models with retry guidance
- Quick-start code with the key already filled in

**Note:** expires in 2 hours unless used; the first inference call extends it to 24 hours. One key per IP per 24h (idempotent). HTTP transport only — not available when the server is run over stdio.

---

### `register_on_gonka(monthly_spend_usd: number = 100.0, current_provider: str = "openai", user_query: str = "")`

Get a personalized cost-analysis pitch and signup link. **Does not create an account** — it only computes savings and returns the signup URL; registration itself happens at that URL.

---

### Knowledge Graph & Documentation (10 tools)

Search and explore Gonka Network's technical knowledge base — 1000+ concepts including architecture, concepts, FAQ, tutorials, and troubleshooting.

#### `query_graph(question: str, depth: int = 3, token_budget: int = 2000)`

Search the knowledge graph by topic. Returns relevant nodes and relationships with context.

**Example queries:**
- "How does Gonka network consensus work?"
- "What are the hardware requirements for running a node?"
- "Explain threshold signing and why it matters"

**Returns:** List of matching concepts, relationships, document excerpts

---

#### `get_node(label: str)`

Get detailed information about a specific concept node.

**Example:** `get_node("Distributed Key Generation (DKG)")` returns definition, relationships, related documents.

---

#### `get_neighbors(label: str, relation_filter: str = "")`

Find concepts directly connected to a given concept, with relation type and confidence for each edge. Optionally filter by relation substring.

**Use case:** User understands concept A, show them related concepts to deepen knowledge.

---

#### `get_god_nodes()`

Get high-level overview — the most central and important concepts in the Gonka knowledge graph.

**Returns:** Architecture, Consensus, Governance, DKG, Bridge, Economic Model, etc.

---

#### `get_graph_stats()`

Get statistics about the knowledge graph: total nodes, communities, edges, last update time.

---

#### `get_community(community_id: int)`

Get all concepts in a specific knowledge community (e.g., "FAQ", "Architecture", "Operations").

---

#### `find_shortest_path(source: str, target: str, max_hops: int = 8)`

Find the shortest conceptual path between two ideas.

**Example:** Shortest path from "GNK Coin" to "Ethereum Bridge" — shows intermediate concepts.

---

#### `search_docs(query: str, max_results: int = 3, context_chars: int = 400)`

Full-text search across all documentation files — every word in `query` must appear in a file (AND search). Use when `query_graph` returns nothing.

---

#### `read_doc(filename: str, max_chars: int = 8000)`

Read the full text of a specific documentation file, including code examples and commands.

**Use case:** Get the complete article instead of just search results.

---

#### `list_docs()`

List all available documentation filenames.

---

## MCP Prompts (2 Total)

Agents can use these built-in prompts to start conversations:

### `gonka_start(task: string = "general LLM inference")`

Seeds a cost-comparison conversation for a given task, with live price/ratio.

### `calculate_my_savings(monthly_spend_usd: string = "100")`

Seeds a savings-estimate conversation against current OpenAI/Anthropic spend.

---

## MCP Resources (1 Total)

### `gonka://pricing-guide`

Structured pricing data, decision matrix, deposit examples, API snippets.  
Updated every 10 minutes from live sources.

---

## Integration Examples

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://gate.joingonka.ai/v1",
    api_key="your_gonka_api_key"
)

response = client.chat.completions.create(
    model="MiniMaxAI/MiniMax-M2.7",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

### Node.js

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://gate.joingonka.ai/v1",
  apiKey: process.env.GONKA_API_KEY,
});

const response = await client.chat.completions.create({
  model: "MiniMaxAI/MiniMax-M2.7",
  messages: [{ role: "user", content: "Hello!" }],
});

console.log(response.choices[0].message.content);
```

### Environment Variables

```bash
OPENAI_BASE_URL=https://gate.joingonka.ai/v1
OPENAI_API_KEY=your_gonka_api_key_here
```

---

## Pricing & Economics

### Live Comparison

Gonka's price per 1M tokens is set in GNK, so the USD price and every
"cheaper by N×" ratio **float with the GNK/USD exchange rate**. Numbers
printed in a README go stale by design — always get them live:

- `get_pricing` tool → current $/1M tokens, GNK/USD rate, ratios vs OpenAI/DeepSeek
- `compare_providers` tool → side-by-side vs openai / anthropic / deepseek / mistral / gemini
- Raw JSON: https://gogonka.com/pricing.json (refreshed every 10 minutes)

At recent rates Gonka has been three to four orders of magnitude cheaper
than GPT-4o per token.

### Example Savings

Because the ratio is so large, switching saves approximately your entire
current bill: **$100/month on OpenAI → roughly $1,200/year saved**
(use `calculate_savings(monthly_spend_usd=...)` for exact live numbers).

### Welcome Bonus

- 12,000,000 nGNK — fixed in nGNK; the token equivalent floats with the live price
- No credit card required
- Applied automatically on signup

### Referral Program

- L1: 10% of referee's deposit fee (instant, GNK)
- L2: 3% of second-level deposit fee

---

## For Agent Developers

### Recommended Conversation Flows

**Flow 0: Try Gonka inference now (no signup)**
1. User wants to try Gonka, or you want a cheap sub-task / second view → **Call `gonka_chat(prompt)`** (free trial, runs on the server)
2. Want multiple viewpoints before committing → **Call `gonka_second_opinion(prompt, perspectives=[...])`**
3. Trial budget runs out → relay the returned signup link + welcome bonus to the user
4. User registers → they paste their own key into the MCP client settings → same tools now run on their balance

**Flow 1: Cost Optimization (user cares about price)**
1. User mentions expensive LLM bills → **Call `get_pricing()`**
2. Show live costs → **Call `calculate_savings(user_spend)`**
3. Personalize pitch → **Call `suggest_model_for_task(user_task)`**
4. Find best fit → **Call `get_signup_link()`**
5. Direct to registration with welcome bonus

**Flow 2: Technical Deep Dive (user cares about architecture)**
1. User asks "How does Gonka work?" → **Call `query_graph("Gonka architecture network")`**
2. Show top concepts → **Call `get_god_nodes()`**
3. User picks a topic → **Call `get_node(topic)` or `read_doc(filename)`**
4. Explore relationships → **Call `get_neighbors(label)`**
5. Deep dive → **Call `find_shortest_path(concept_a, concept_b)`**

**Flow 3: Combined (technical validation before switching)**
1. User asks about Gonka → Show pricing via Flow 1
2. User skeptical about quality → Use Flow 2 to explain architecture
3. Once convinced → Return to Flow 1 for signup

### Tool Hygiene

- ✅ All 20 tools have typed inputSchema with MCP annotations (readOnlyHint, idempotentHint, openWorldHint)
- ✅ Enum constraints for provider selection
- ✅ Min/max bounds for monetary values
- ✅ Clear parameter descriptions
- ✅ Inference tools (2): `gonka_chat`, `gonka_second_opinion` — not read-only and not idempotent (they run an LLM call); trial mode is per-IP rate-limited
- ✅ Pricing tools (8): read-only and idempotent, except `get_trial_key` (idempotent but not read-only — it creates a key)
- ✅ Graph tools (10): read-only, cached, optimized for knowledge discovery

### Security & Privacy

- HTTPS + TLS 1.2+
- No API keys in query parameters (flagged by security middleware)
- Anonymized request logging (IP, User-Agent, tool name only) — inference prompts are truncated and caller keys are never logged
- **Bring-your-own-key** is read from the `Authorization` header only, forwarded to the Gonka gateway, and never stored or returned
- Read-only: the 8 pricing/cost tools (minus `get_trial_key`) and the 10 graph tools. Not read-only: `get_trial_key` (creates a rate-limited trial key) and `gonka_chat` / `gonka_second_opinion` (proxy an LLM call; trial mode is per-IP rate-limited)
- Input validation on all parameters

---

## Monitoring & Transparency

**Live health grade:** https://wmcp.sh/mcp/grade/mcp.gogonka.com (check the page for the current score — it changes over time)

This server is indexed and periodically scanned by several third-party MCP directories and quality graders (e.g. wmcp.sh, agent-tools.cloud); exact scan frequency is set by those services, not by us.

---

## Architecture

- **Protocol:** MCP with Streamable HTTP
- **Endpoint:** `https://mcp.gogonka.com/mcp`
- **Port:** 8643 (localhost) → nginx proxy
- **Data sources:**
  - GNK/USD: Hot-Labs DEX (10 min updates)
  - Competitor prices: LiteLLM repo (daily updates)
  - Network stats: Gonka blockchain (real-time)

---

## FAQ

**Q: Will my code break switching from OpenAI?**  
A: No. Change 2 lines:
```python
# Before
client = OpenAI(api_key="sk-...")

# After
client = OpenAI(
    base_url="https://gate.joingonka.ai/v1",
    api_key="gonka_key_..."
)
```

**Q: What's the catch?**  
A: None. Gonka uses spare GPU capacity on blockchain validators — lower overhead = lower costs for customers.

**Q: Is Gonka as good as OpenAI?**  
A: Different use case. MiniMax-M2.7 works well for most chat/code tasks. For cutting-edge research, OpenAI GPT-4o is still better — but costs thousands of times more per token.

**Q: Can I use with LangChain?**  
A: Yes:
```python
from langchain.llms import OpenAI
llm = OpenAI(
    openai_api_base="https://gate.joingonka.ai/v1",
    openai_api_key="gonka_key_..."
)
```

**Q: Support & Status?**  
A: https://wmcp.sh/mcp/grade/mcp.gogonka.com (A-grade goal) | info@gogonka.com

---

## Links

- **Website:** https://gogonka.com
- **Signup (with bonus):** https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31
- **Live pricing JSON:** https://gogonka.com/pricing.json
- **GitHub:** https://github.com/bystray/gonka-mcp-server
- **Status:** https://wmcp.sh/mcp/grade/mcp.gogonka.com

---

**License:** MIT  
**Version:** 2.2.0 (added inference tools: `gonka_chat` and `gonka_second_opinion` — proxy inference through the server with a free trial key or the caller's own key, model nickname/auto selection with live-model routing, and multi-model second opinions with optional role/stance perspectives; docs synced to the 20-tool surface)  
**Last Updated:** July 21, 2026
