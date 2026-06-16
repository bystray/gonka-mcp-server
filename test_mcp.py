#!/usr/bin/env python3
"""
Gonka MCP Conversion Test
Uses Gonka Network (Qwen3-235B) to simulate real users and evaluate tool quality.
"""

import json
import urllib.request
import sys

MCP_URL    = "https://mcp.gogonka.com/mcp"
GONKA_URL  = "https://gate.joingonka.ai/v1"
GONKA_KEY  = "jg-0852d7d026b82e4f6c7e850c3f4e3a3fa78e4e3af300fe149ebe2a19d9de206d"
MODEL      = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"
SIGNUP_URL = "gate.joingonka.ai/register"


# ── MCP helpers ───────────────────────────────────────────────────────────────

def mcp_call(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def get_tools():
    resp = mcp_call("tools/list")
    return resp.get("result", {}).get("tools", [])


def call_tool(name, arguments=None):
    resp = mcp_call("tools/call", {"name": name, "arguments": arguments or {}})
    content = resp.get("result", {}).get("content", [{}])
    return json.loads(content[0].get("text", "{}"))


# ── Agent loop via OpenAI SDK → Gonka ────────────────────────────────────────

def run_persona(client, tools_schema, message):
    messages = [{"role": "user", "content": message}]
    tool_calls_made = []

    for _ in range(5):
        resp = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            tools=tools_schema,
            messages=messages,
        )
        choice = resp.choices[0]

        if choice.finish_reason == "stop":
            return tool_calls_made, choice.message.content or ""

        if choice.finish_reason == "tool_calls":
            messages.append({"role": "assistant", "content": choice.message.content,
                              "tool_calls": [tc.model_dump() for tc in choice.message.tool_calls]})
            for tc in choice.message.tool_calls:
                tool_calls_made.append(tc.function.name)
                args = json.loads(tc.function.arguments or "{}")
                result = call_tool(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

    return tool_calls_made, "[max rounds]"


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(expected_tools, tool_calls_made, response_text):
    score, max_score = 0, 0
    goods, issues = [], []

    # Правильные инструменты вызваны?
    for t in expected_tools:
        max_score += 2
        if t in tool_calls_made:
            score += 2
            goods.append(f"✓ вызван {t}")
        else:
            issues.append(f"✗ не вызван {t} (вызваны: {tool_calls_made})")

    # Ссылка регистрации в ответе?
    max_score += 3
    if SIGNUP_URL in response_text:
        score += 3
        goods.append("✓ ссылка регистрации показана")
    else:
        issues.append("✗ ссылка регистрации отсутствует")

    # Цена/экономия упомянута?
    max_score += 2
    price_keywords = ["$0.00", "cheaper", "1M tokens", "savings", "save", "per 1M", "x cheaper"]
    if any(k.lower() in response_text.lower() for k in price_keywords):
        score += 2
        goods.append("✓ цена или экономия упомянута")
    else:
        issues.append("✗ цена не упомянута")

    pct = round(score / max_score * 100) if max_score else 0
    grade = "🟢 Отлично" if pct >= 80 else "🟡 Хорошо" if pct >= 50 else "🔴 Плохо"
    return score, max_score, pct, grade, goods, issues


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    from openai import OpenAI
    client = OpenAI(base_url=GONKA_URL, api_key=GONKA_KEY)

    print("Загружаем инструменты с MCP...")
    tools_raw = get_tools()
    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools_raw
    ]
    print(f"Инструментов: {len(tools_schema)} — {[t['function']['name'] for t in tools_schema]}\n")

    personas = [
        {
            "name": "💸 Стартапер с болью",
            "message": "I'm spending about $300/month on OpenAI API. Is there a cheaper alternative?",
            "expected": ["calculate_savings"],
        },
        {
            "name": "🤔 Выбирает модель",
            "message": "I need to build a customer support chatbot. Which AI model should I use to keep costs low?",
            "expected": ["suggest_model_for_task"],
        },
        {
            "name": "🔍 Сравнивает с Anthropic",
            "message": "How does Gonka Network compare to Anthropic Claude pricing?",
            "expected": ["compare_providers"],
        },
        {
            "name": "🚀 Готов подключиться",
            "message": "I want to sign up for Gonka Network and get an API key. How do I start?",
            "expected": ["get_signup_link"],
        },
        {
            "name": "📊 Хочет цены и модели",
            "message": "What models does Gonka Network offer and what are the current prices?",
            "expected": ["get_available_models"],
        },
    ]

    total_score, total_max = 0, 0

    for p in personas:
        print(f"{'='*65}")
        print(f"Персонаж: {p['name']}")
        print(f"Вопрос:   {p['message']}")
        print()

        try:
            tool_calls, response = run_persona(client, tools_schema, p["message"])
        except Exception as e:
            print(f"  ❌ Ошибка: {e}\n")
            continue

        score, max_score, pct, grade, goods, issues = evaluate(p["expected"], tool_calls, response)

        print(f"Вызваны:  {tool_calls if tool_calls else '(нет)'}")
        print(f"Ответ:\n{response[:700]}{'...' if len(response) > 700 else ''}")
        print()
        print(f"Оценка: {grade} {score}/{max_score} ({pct}%)")
        for g in goods:
            print(f"  {g}")
        for i in issues:
            print(f"  {i}")

        total_score += score
        total_max   += max_score
        print()

    print(f"{'='*65}")
    pct = round(total_score / total_max * 100) if total_max else 0
    overall = "🟢 Отлично" if pct >= 80 else "🟡 Хорошо" if pct >= 50 else "🔴 Нужна доработка"
    print(f"ИТОГОВАЯ ОЦЕНКА: {total_score}/{total_max} ({pct}%) — {overall}")


if __name__ == "__main__":
    main()
