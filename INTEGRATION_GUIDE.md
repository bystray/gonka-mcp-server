# Gonka Network MCP - Integration Guide for AI Agents

Complete setup instructions for different AI agents and frameworks.

🔗 **MCP Server:** `https://mcp.gogonka.com/mcp`

---

## Quick Start

**No API key needed. Public access.**

All integrations follow the same pattern:
1. Add MCP server URL: `https://mcp.gogonka.com/mcp`
2. Agent automatically discovers available tools
3. Call `get_pricing()`, `calculate_savings()`, etc.

---

## 🤖 Claude Code (VS Code / JetBrains)

### Setup

1. Open Claude Code settings (⚙️)
2. Go to **Tools** → **MCP Servers**
3. Add new server:

```json
{
  "name": "gonka-pricing",
  "url": "https://mcp.gogonka.com/mcp"
}
```

4. Save and reconnect Claude

### Usage in Chat

```
@gonka-pricing Help me calculate savings by switching from OpenAI to Gonka.
Current spend: $500/month

→ Claude will call calculate_savings(500) and show results
```

---

## 🖱️ Cursor

### Setup

#### Option A: Cursor Settings (Recommended)

1. **Cursor Settings** → **Features** → **Tools** → **MCP**
2. Add server:

```json
{
  "name": "gonka-mcp",
  "url": "https://mcp.gogonka.com/mcp"
}
```

3. Restart Cursor

#### Option B: .cursor/config.json

Edit `~/.cursor/config.json`:

```json
{
  "tools": [
    {
      "type": "mcp",
      "name": "gonka",
      "url": "https://mcp.gogonka.com/mcp"
    }
  ]
}
```

### Usage

Type in chat:
```
@gonka-mcp Compare Gonka with OpenAI pricing
```

Cursor will automatically call available tools.

---

## 🐍 LangChain

### Setup

```python
from langchain_community.tools.mcp import MCPToolkit

# Initialize toolkit (no auth needed)
toolkit = MCPToolkit(
    server_url="https://mcp.gogonka.com/mcp"
)

# Get all available tools
tools = toolkit.get_tools()

# Use in agent
from langchain.agents import initialize_agent, AgentType

agent = initialize_agent(
    tools=tools,
    llm=your_llm_instance,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)
```

### Example: Calculate Savings

```python
result = agent.run(
    "How much would I save per year if I switch from OpenAI "
    "and currently spend $1000 per month?"
)
print(result)
```

Output:
```
Calling tool: calculate_savings with args: {'monthly_spend_usd': 1000}
...
Annual savings: $26,500 (99.8% cheaper than OpenAI)
```

---

## 🚀 Hermes Agent

### Setup

Edit your Hermes Agent configuration:

```yaml
# hermes-config.yaml or similar

mcp_servers:
  gonka_pricing:
    url: https://mcp.gogonka.com/mcp
    enabled: true
    # No authentication needed (public access)

agent_workflows:
  - name: "pricing_advisor"
    description: "Compare LLM pricing and calculate savings"
    tools:
      - mcp: gonka_pricing
```

### Usage in Agent

```python
from hermes_agent import Agent

agent = Agent(config_file="hermes-config.yaml")

result = agent.execute_task(
    "Get current Gonka Network pricing and compare with OpenAI"
)
```

### YAML Example

```yaml
tasks:
  - name: "analyze_cost_savings"
    description: "Analyze potential cost savings"
    steps:
      - tool: mcp.gonka_pricing.get_pricing
        output_var: gonka_pricing
      
      - tool: mcp.gonka_pricing.calculate_savings
        params:
          monthly_spend_usd: 1500
        output_var: savings_analysis
      
      - action: log
        message: "Annual savings: ${savings_analysis.annual_savings_usd}"
```

---

## ⚙️ n8n Workflow

### Setup

1. Open n8n editor
2. **Credentials** → Create MCP credential:
   - Name: `Gonka MCP`
   - Type: `MCP`
   - URL: `https://mcp.gogonka.com/mcp`
   - Authentication: None

3. In workflow, add nodes:

#### Node 1: MCP Call

```
Node Type: MCP
Credential: Gonka MCP
Method: Call Tool
Tool Name: get_pricing
```

#### Node 2: Process Response

```
Input from: Node 1
Logic: Extract USD prices and format
```

#### Node 3: Conditional

```
If price < $0.001 per 1M tokens:
  → Notify: "Great deal found"
Else:
  → Log: "Check other providers"
```

### Example Workflow JSON

```json
{
  "nodes": [
    {
      "name": "Get Gonka Pricing",
      "type": "mcp",
      "typeVersion": 1,
      "parameters": {
        "resource": "call_tool",
        "tool": "get_pricing",
        "credentials": "gonka_mcp"
      }
    },
    {
      "name": "Format Prices",
      "type": "code",
      "parameters": {
        "code": "return {pricing: $('Get Gonka Pricing').json().result}"
      }
    }
  ]
}
```

---

## 🧠 Custom Integration (HTTP)

If your agent doesn't have MCP support yet, call the server directly:

### Python

```python
import requests
import json

def call_gonka_mcp(tool_name, **params):
    url = "https://mcp.gogonka.com/mcp"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params
        }
    }
    
    response = requests.post(url, json=payload)
    return response.json()

# Get pricing
pricing = call_gonka_mcp("get_pricing")
print(f"Gonka price: ${pricing['result']['usd_per_1m_tokens']}/1M tokens")

# Calculate savings
savings = call_gonka_mcp("calculate_savings", monthly_spend_usd=500)
print(f"Annual savings: ${savings['result']['annual_savings_usd']}")
```

### JavaScript/Node.js

```javascript
async function callGonkaMCP(toolName, params) {
  const response = await fetch('https://mcp.gogonka.com/mcp', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: toolName,
        arguments: params
      }
    })
  });
  
  return response.json();
}

// Get pricing
const pricing = await callGonkaMCP('get_pricing');
console.log(`Gonka: $${pricing.result.usd_per_1m_tokens}/1M tokens`);

// Calculate savings
const savings = await callGonkaMCP('calculate_savings', {
  monthly_spend_usd: 500
});
console.log(`Save: $${savings.result.annual_savings_usd}/year`);
```

### cURL

```bash
# Get pricing
curl -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_pricing",
      "arguments": {}
    }
  }' | jq '.result.usd_per_1m_tokens'

# Calculate savings for $1000/month spend
curl -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "calculate_savings",
      "arguments": {"monthly_spend_usd": 1000}
    }
  }' | jq '.result'
```

---

## ⚠️ Common Mistakes

### ❌ WRONG: Sending API key in URL

```
❌ POST https://mcp.gogonka.com/mcp?api_key=YOUR_KEY
❌ POST https://mcp.gogonka.com/mcp?auth=bearer%20TOKEN
```

**This server doesn't require authentication.** API keys in URLs are a security risk.

### ❌ WRONG: Adding Authorization header

```
❌ Authorization: Bearer YOUR_KEY
```

This MCP server is public. Don't add credentials.

### ✅ RIGHT: Just call the endpoint

```
✅ POST https://mcp.gogonka.com/mcp (no auth)
```

---

## 🐛 Troubleshooting

### "MCP server not found" / Connection refused

```bash
# Check if server is running
curl https://mcp.gogonka.com/mcp -v

# Should see 200 OK or valid MCP response
```

### "Tool not found" / Invalid tool name

Available tools:
- `get_pricing`
- `get_available_models`
- `compare_providers`
- `calculate_savings`
- `get_signup_link`

Verify tool name in tool calling docs.

### "Request timeout"

Server response time is usually < 100ms. If timing out:
- Check internet connection
- Verify firewall allows HTTPS to mcp.gogonka.com
- Try direct curl test above

### Pricing data seems stale

Pricing updates every 10 minutes from pricing.json.

```bash
# Check last update time
curl https://gogonka.com/pricing.json | jq '.data_last_updated'
```

---

## 📊 Monitoring

To check if your agent is using the MCP server correctly:

```bash
# View recent MCP activity
ssh your_server "journalctl -u gonka-mcp.service -n 50 --no-pager"

# Check for any security warnings (API keys in URLs)
ssh your_server "journalctl -u gonka-mcp.service | grep SECURITY"
```

---

## 📚 Related Resources

- **MCP Spec:** https://spec.modelcontextprotocol.io/
- **Gonka Pricing:** https://gogonka.com/pricing.json
- **Setup Guide:** https://gogonka.com/setup.sh
- **Agent Onboarding:** https://gogonka.com/llms.txt

---

**Questions?** Check MCP server logs: `journalctl -u gonka-mcp.service`
