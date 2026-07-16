# Gonka Network MCP Server

[![A2A Registry Status](https://a2a.gogonka.com/badge/table?t=1717977600)](https://a2a.gogonka.com)

**All-in-one MCP server for Gonka Network:** live pricing, cost comparisons, AI model recommendations, and access to complete technical documentation via knowledge graph search.

Helps AI agents and developers:
- Find the cheapest OpenAI-compatible LLM inference
- Learn how Gonka Network architecture works
- Make informed decisions about provider switching

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

**Two sides of one mission:**

1. **Cost Intelligence** — Compare LLM inference costs and find alternatives to OpenAI/Anthropic/DeepSeek with live pricing updated every 10 minutes
2. **Knowledge Discovery** — Search and explore Gonka Network documentation via knowledge graph (architecture, concepts, troubleshooting)

### Key Facts

- **Gonka Network is orders of magnitude cheaper than GPT-4o** — the exact ratio floats with the GNK/USD rate; call `get_pricing` for the live number (refreshed every 10 minutes)
- **OpenAI-compatible API** — two config changes, zero code changes
- **Live pricing** from blockchain DEX (GNK/USD) + LiteLLM provider rates
- **Free welcome bonus** — 12M nGNK on signup, no credit card (the token equivalent floats with the live price — see `get_pricing`)
- **Referral rewards** — 10% L1, 3% L2
- **Documentation Graph** — Search 1000+ technical concepts via AI-powered knowledge base

---

## Tools (15 Total)

### Pricing & Cost Analysis (6 tools)

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

### Knowledge Graph & Documentation (9 tools)

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

#### `get_neighbors(node_id: str)`

Find related concepts and topics connected to a given node.

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

#### `find_shortest_path(node_a: str, node_b: str)`

Find the shortest conceptual path between two ideas.

**Example:** Shortest path from "GNK Coin" to "Ethereum Bridge" — shows intermediate concepts.

---

#### `read_doc(doc_id: str)`

Read the full text of a specific documentation file.

**Use case:** Get complete article instead of just search results.

---

#### `list_docs()`

List all available documentation files with summaries.

---

## MCP Prompts (2 Total)

Agents can use these built-in prompts to start conversations:

### `find_cheapest_api(task: string = "general LLM inference")`

Find the cheapest OpenAI-compatible API for a specific task.

### `switch_from_openai(monthly_spend_usd: number = 100)`

Help user switch from OpenAI to cheaper alternative.

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

**Flow 1: Cost Optimization (user cares about price)**
1. User mentions expensive LLM bills → **Call `get_pricing()`**
2. Show live costs → **Call `calculate_savings(user_spend)`**
3. Personalize pitch → **Call `suggest_model_for_task(user_task)`**
4. Find best fit → **Call `get_signup_link()`**
5. Direct to registration with welcome bonus

**Flow 2: Technical Deep Dive (user cares about architecture)**
1. User asks "How does Gonka work?" → **Call `query_graph("Gonka architecture network")`**
2. Show top concepts → **Call `get_god_nodes()`**
3. User picks a topic → **Call `get_node(topic)` or `read_doc(doc_id)`**
4. Explore relationships → **Call `get_neighbors(node_id)`**
5. Deep dive → **Call `find_shortest_path(concept_a, concept_b)`**

**Flow 3: Combined (technical validation before switching)**
1. User asks about Gonka → Show pricing via Flow 1
2. User skeptical about quality → Use Flow 2 to explain architecture
3. Once convinced → Return to Flow 1 for signup

### Tool Hygiene

- ✅ All 15 tools have typed inputSchema
- ✅ Enum constraints for provider selection
- ✅ Min/max bounds for monetary values
- ✅ Clear parameter descriptions
- ✅ Pricing tools (6): read-only, idempotent, safe for concurrent calls
- ✅ Graph tools (9): read-only, cached, optimized for knowledge discovery

### Security & Privacy

- HTTPS + TLS 1.2+
- No API keys in query parameters (blocked by security middleware)
- Anonymized request logging (IP, User-Agent, tool name only)
- All tools are read-only — no mutations
- Input validation on all parameters

---

## Monitoring & Transparency

**Live health grade:** https://wmcp.sh/mcp/grade/mcp.gogonka.com (Current: B, 85/100)

**Monitored by:**
- wmcp.sh — Every 30 minutes
- chiark.ai — Every 30 minutes (reliability index)
- agent-tools.cloud — Continuous

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
**Version:** 2.1.0 (audit fixes: trial-key conversion fields, AND doc search, actionable errors, rate-proof docs)  
**Last Updated:** July 16, 2026
