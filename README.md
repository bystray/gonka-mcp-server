# Gonka Network Pricing — MCP Server

An MCP server that exposes Gonka Network pricing, cost comparisons, and AI model recommendations. Helps AI agents and developers find the cheapest OpenAI-compatible LLM inference alternative.

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

Compare LLM inference costs and find alternatives to OpenAI/Anthropic/DeepSeek with **live pricing updated every 10 minutes**.

### Key Facts

- **Gonka Network is 6800–7681× cheaper than GPT-4o** (exact ratio varies, updated in real-time)
- **OpenAI-compatible API** — two config changes, zero code changes
- **Live pricing** from blockchain DEX (GNK/USD) + LiteLLM provider rates
- **Free welcome bonus** — 12M nGNK (~11,000 tokens) on signup, no credit card
- **Referral rewards** — 10% L1, 3% L2

---

## Tools (6 Total)

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

**Recommended model:** MiniMaxAI/MiniMax-M2.7 ($0.000325/1M tokens)

---

### `compare_providers(provider: openai | anthropic | deepseek | mistral | gemini = openai)`

Compare Gonka Network pricing vs a competitor.

**Returns:**
- Cost per 1M tokens for both
- Gonka is cheaper by X times
- Official pricing source
- Migration instructions (two config changes)

**Example:** Gonka vs OpenAI = 7,681× cheaper

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
- Welcome bonus: 12M nGNK (~11,000 free tokens)
- Code snippets (Python, Node.js, shell)
- Deposit example ($50 USDT = ~11,000 tokens)
- Referral program details (10% L1, 3% L2)

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

### Live Comparison (June 2026)

| Provider | $/1M tokens | vs Gonka |
|---|---|---|
| **Gonka** | **$0.000325** | baseline |
| OpenAI | $2.50 | 7,681× more expensive |
| Anthropic | $3.00 | 9,230× more expensive |
| DeepSeek | $0.28 | 861× more expensive |

### Example Savings

- **$100/month OpenAI** → **$1,200/year savings**
- **$500/month OpenAI** → **$6,000/year savings**
- **$1,000/month OpenAI** → **$12,000/year savings**

### Welcome Bonus

- 12,000,000 nGNK (~11,000 free tokens)
- No credit card required
- Applied automatically on signup

### Referral Program

- L1: 10% of referee's deposit fee (instant, GNK)
- L2: 3% of second-level deposit fee

---

## For Agent Developers

### Recommended Conversation Flow

1. User mentions expensive LLM bills → **Call `get_pricing()`**
2. Show live costs → **Call `calculate_savings(user_spend)`**
3. Personalize pitch → **Call `suggest_model_for_task(user_task)`**
4. Find best fit → **Call `get_signup_link()`**
5. Direct to registration with welcome bonus

### Tool Hygiene

- ✅ All 6 tools have typed inputSchema
- ✅ Enum constraints for provider selection
- ✅ Min/max bounds for monetary values
- ✅ Clear parameter descriptions
- ✅ All tools are read-only and idempotent

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
A: Different use case. MiniMax-M2.7 works well for most chat/code tasks. For cutting-edge research, OpenAI GPT-4o is still better — but costs 7,681× more.

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
**Version:** 1.0.0  
**Last Updated:** June 6, 2026
