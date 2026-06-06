# Gonka Network MCP Server

**MCP (Model Context Protocol) server for Gonka Network pricing information and cost comparisons.**

🔗 **Endpoint:** `https://mcp.gogonka.com/mcp`  
🌐 **Status:** Public, no authentication required  
📊 **Data Updated:** Every 10 minutes from `pricing.json`

---

## ⚠️ SECURITY WARNING

**⛔ DO NOT send API keys, credentials, or secrets in URL query parameters.**

API keys in URLs are visible in:
- Web server access logs
- Browser history
- HTTP Referer headers
- Firewall/CDN logs
- Proxy logs

**This MCP server does NOT require authentication.** All tools are publicly accessible.

---

## Usage

### For AI Agents (Claude Code, Cursor, LangChain, Hermes Agent, etc.)

Configure MCP connection:

```json
{
  "tools": [
    {
      "type": "mcp",
      "name": "gonka-pricing",
      "url": "https://mcp.gogonka.com/mcp"
    }
  ]
}
```

**No API key needed. No authentication.**

### Direct HTTP Calls

```bash
curl -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

---

## Available Tools

### 1. `get_pricing()`

Get current Gonka Network pricing data.

**Returns:**
- USD cost per 1M tokens
- GNK exchange rate (USD/GNK)
- Comparison ratios vs OpenAI, Anthropic, DeepSeek
- $50 deposit example
- Data freshness timestamp

### 2. `get_available_models()`

List all models available on Gonka Network gateway.

**Returns:**
- Model IDs (same as used in API calls)
- Status (available / restricted)
- Access requirements

### 3. `compare_providers(provider: str)`

Compare Gonka pricing against competitors.

**Args:**
- `provider`: "openai", "anthropic", or "deepseek"

**Returns:**
- USD per 1M tokens for both
- Savings ratio
- Official pricing source links

### 4. `calculate_savings(monthly_spend_usd: float)`

Calculate monthly/annual savings by switching to Gonka.

**Args:**
- `monthly_spend_usd`: Your current monthly LLM API spend

**Returns:**
- Monthly savings (USD)
- Annual savings (USD)
- Break-even point for deposit fee
- Signup link with bonus tokens

### 5. `get_signup_link()`

Get Gonka Network registration link with referral bonus.

**Returns:**
- Registration URL
- Welcome bonus details (12M nGNK ≈ 11,000 free tokens)
- Quick-start code examples (Python, env vars)
- Referral program details

---

## Integration Examples

### Claude Code

```yaml
# claude.settings.json (or IDE config)
tools:
  - type: mcp
    url: https://mcp.gogonka.com/mcp
```

### Cursor

Add to cursor settings:

```json
{
  "tools": [
    {
      "name": "gonka-mcp",
      "type": "mcp",
      "url": "https://mcp.gogonka.com/mcp"
    }
  ]
}
```

### LangChain

```python
from langchain.tools import tool
from langchain_community.tools.mcp import MCPToolkit

# No API key needed
toolkit = MCPToolkit(
    server_url="https://mcp.gogonka.com/mcp"
)
tools = toolkit.get_tools()
```

### Hermes Agent

```yaml
# hermes-agent config
mcp_servers:
  - name: gonka_pricing
    url: https://mcp.gogonka.com/mcp
    # No authentication needed
```

### n8n

Create n8n workflow with MCP node:

```
Input → MCP Fetch Tools → MCP Call Tool (get_pricing) → Process
```

URL: `https://mcp.gogonka.com/mcp`  
Auth: None

---

## Logging & Security

### What We Log

✅ Logged (safe for audit):
- Tool name called
- Client IP (via X-Forwarded-For)
- User-Agent
- Response time (ms)
- Timestamp

❌ Never Logged:
- Full URLs with query parameters
- API keys or credentials
- Request/response bodies (tool data logged separately, never secrets)

### Security Features

- Uvicorn access logs **disabled** (prevents full URL logging)
- Security middleware detects API keys in URLs and logs warnings
- HTTPS only (via nginx)
- Read-only pricing data (no write endpoints)

---

## Data Sources

- **Pricing:** Updated from `/var/www/gogonka/pricing.json` every 10 minutes
- **Models:** Live from Gonka Network gateway
- **Exchange rates:** GNK/USD from `pricing.json` (market data)
- **Competitor prices:** Cached from official pricing pages

---

## Troubleshooting

### "Invalid request" / 400 errors

Check MCP protocol version. This server supports MCP v1 (2024-11).

```bash
# Verify server is responding
curl https://mcp.gogonka.com/mcp
```

### Slow responses

Pricing data is updated every 10 minutes. If you get stale data:
```bash
# Pricing.json was last updated:
curl https://gogonka.com/pricing.json | jq '.data_last_updated'
```

### Connection issues

Server listens on `http://127.0.0.1:8643` internally, proxied via nginx to `https://mcp.gogonka.com/mcp`.

Check nginx status:
```bash
sudo systemctl status nginx
```

Check MCP server status:
```bash
sudo systemctl status gonka-mcp.service
```

---

## API Changelog

### v1 (Current)

- 5 tools: pricing, models, compare, savings, signup
- Public access, no authentication
- HTTPS only
- Pricing updated every 10 minutes

---

## Support

- **Documentation:** https://gogonka.com/llms.txt
- **Setup Guide:** https://gogonka.com/setup.sh
- **Issues/Feedback:** See MCP server logs via `journalctl -u gonka-mcp.service`

---

**Last Updated:** 2026-06-05  
**Maintainer:** Gonka Network
