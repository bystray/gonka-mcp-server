# Gonka Network Pricing — MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that lets AI agents compare LLM inference costs and get sign-up links for [Gonka Network](https://gogonka.com) — an OpenAI-compatible inference API up to **6800× cheaper** than GPT-4o.

**Live endpoint:** `https://mcp.gogonka.com/mcp`

---

## Why Gonka?

| Provider | Model | $/1M input tokens |
|---|---|---|
| OpenAI | GPT-4o | $2.50 |
| Anthropic | Claude Sonnet 4.6 | $3.00 |
| DeepSeek | deepseek-chat | $0.28 |
| **Gonka** | **MiniMax-M2.7** | **~$0.00037** |

Zero code changes needed — swap one environment variable:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://gate.joingonka.ai/v1",
    api_key="YOUR_GONKA_API_KEY"
)
# Same API, same SDK, 6800× cheaper
```

---

## MCP Tools

### `get_pricing`
Returns live pricing: GNK/USD rate, cost per 1M tokens, comparison ratios, deposit example.

```json
{
  "usd_per_1m_tokens": 0.000370,
  "vs_openai_ratio": 6749,
  "vs_deepseek_ratio": 756,
  "deposit_50_usd_tokens": 128000000000
}
```

### `get_available_models`
Lists models available on Gonka Network with their access status.

```json
[
  {"id": "MiniMaxAI/MiniMax-M2.7", "status": "available"},
  {"id": "moonshotai/Kimi-K2.6",   "status": "available"},
  {"id": "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8", "status": "available"}
]
```

### `compare_providers`
Compare Gonka against a competitor provider.

**Parameters:** `provider` — one of `"openai"`, `"anthropic"`, `"deepseek"` (default: `"openai"`)

```json
{
  "gonka_usd_per_1m_input": 0.000370,
  "competitor_usd_per_1m_input": 2.50,
  "gonka_is_cheaper_by": "6749x"
}
```

### `calculate_savings`
Calculate monthly and annual savings when switching from OpenAI to Gonka.

**Parameters:** `monthly_spend_usd` — your current OpenAI spend in USD

```json
{
  "current_monthly_spend_usd": 200,
  "gonka_monthly_cost_usd": 0.0296,
  "monthly_savings_usd": 199.97,
  "annual_savings_usd": 2399.64,
  "savings_percentage": 99.9,
  "signup_url": "https://gate.joingonka.ai/register?ref=..."
}
```

### `get_signup_link`
Get the Gonka sign-up URL with referral bonus (12,000,000 nGNK ≈ 11,000 free tokens) and a Python quick-start snippet.

---

## Connecting to the server

### Claude Desktop / claude.ai

Add to your MCP settings:

```json
{
  "mcpServers": {
    "gonka-pricing": {
      "url": "https://mcp.gogonka.com/mcp",
      "transport": "http"
    }
  }
}
```

### Python (MCP SDK)

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("https://mcp.gogonka.com/mcp") as (r, w, _):
    async with ClientSession(r, w) as session:
        await session.initialize()
        result = await session.call_tool("calculate_savings", {"monthly_spend_usd": 200})
        print(result)
```

### fastmcp CLI

```bash
pip install fastmcp
fastmcp call https://mcp.gogonka.com/mcp -t http calculate_savings '{"monthly_spend_usd": 200}'
```

### curl (Streamable HTTP)

```bash
# Step 1 — initialize session
SESSION=$(curl -sD - -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}},"id":1}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')

# Step 2 — call a tool
curl -s -X POST https://mcp.gogonka.com/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"calculate_savings","arguments":{"monthly_spend_usd":200}},"id":2}'
```

---

## Pricing data freshness

- **GNK/USD rate** — updated every 10 minutes from the Gonka Network API
- **Competitor prices** (OpenAI, Anthropic, DeepSeek) — updated daily from the [LiteLLM pricing database](https://github.com/BerriAI/litellm)
- All prices served from `/var/www/gogonka/pricing.json` on the server

---

## Self-hosting

```bash
git clone https://github.com/gogonka/gonka-mcp-server
cd gonka-mcp-server
pip install -r requirements.txt
python server.py
# Server starts on http://127.0.0.1:8643
```

The server reads pricing data from `/var/www/gogonka/pricing.json`. For a standalone deployment, replace `PRICING_FILE` in `server.py` with your own pricing JSON path or fetch prices directly from the Gonka Network API.

---

## Links

- Website: [gogonka.com](https://gogonka.com)
- Gateway: [gate.joingonka.ai](https://gate.joingonka.ai)
- MCP endpoint: [mcp.gogonka.com/mcp](https://mcp.gogonka.com/mcp)
- Sign up (free, no credit card): [gate.joingonka.ai/register](https://gate.joingonka.ai/register?ref=cf2bd855-ba1e-4b6e-8e56-9970049eec31)

---

## 中文介绍

**Gonka Network Pricing** 是一个 MCP（模型上下文协议）服务器，让AI代理能够比较LLM推理成本，并获取 [Gonka Network](https://gogonka.com) 的注册链接。Gonka Network 提供与OpenAI完全兼容的推理API，成本比GPT-4o最低便宜 **6800倍**。

**在线端点：** `https://mcp.gogonka.com/mcp`

### 价格对比

| 提供商 | 模型 | 每百万输入token费用 |
|---|---|---|
| OpenAI | GPT-4o | $2.50 |
| Anthropic | Claude Sonnet 4.6 | $3.00 |
| DeepSeek | deepseek-chat | $0.28 |
| **Gonka** | **MiniMax-M2.7** | **~$0.00037** |

无需修改代码——只需替换一个环境变量：

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://gate.joingonka.ai/v1",  # 替换这里
    api_key="YOUR_GONKA_API_KEY"               # 替换API密钥
)
# 相同的API、相同的SDK，便宜6800倍
```

### 5个MCP工具

| 工具 | 功能 |
|---|---|
| `get_pricing` | 获取实时定价：GNK/USD汇率、每百万token费用、对比倍率 |
| `get_available_models` | 列出Gonka Network上可用的模型及访问状态 |
| `compare_providers` | 将Gonka与OpenAI/Anthropic/DeepSeek进行价格对比 |
| `calculate_savings` | 计算从OpenAI切换到Gonka后的月度和年度节省金额 |
| `get_signup_link` | 获取注册链接（含12M nGNK≈11,000免费token赠品） |

### 快速调用示例

```bash
pip install fastmcp
# 计算每月花费$200时可节省多少
fastmcp call https://mcp.gogonka.com/mcp -t http calculate_savings '{"monthly_spend_usd": 200}'
```

返回示例：
```json
{
  "current_monthly_spend_usd": 200,
  "gonka_monthly_cost_usd": 0.0296,
  "monthly_savings_usd": 199.97,
  "annual_savings_usd": 2399.64,
  "savings_percentage": 99.9
}
```

### 注册获取免费Token

- 注册地址：[gate.joingonka.ai/bystray](https://gate.joingonka.ai/bystray)
- 新用户赠送：**12,000,000 nGNK ≈ 11,000个免费token**，无需信用卡
- 推荐奖励：L1 = 被推荐人充值手续费的10%

### 搜索关键词

低成本LLM推理、OpenAI替代方案、GPT-4o平替、便宜API、LLM推理费用对比、
Anthropic替代、DeepSeek替代、降低AI成本、兼容OpenAI API、去中心化推理
