"""
Langfuse prompt-management wrappers.

Reuses the same Langfuse client already instantiated for tracing in
server.py (get_client() is a singleton keyed on the configured project, so a
second call here returns that same instance — no extra credentials needed).

get_prompt()'s built-in `fallback=` already covers the "Langfuse unreachable
/ prompt not yet created" case: on fetch failure it returns a PromptClient
wrapping the fallback text/messages, so callers never need their own
try/except. Fallback text has no {{...}} placeholders (it's the fully
rendered current string), so .compile() is a no-op passthrough for it.
"""
from __future__ import annotations

import logging

try:
    from langfuse import get_client
    _langfuse = get_client()
except Exception as _e:  # missing keys must never take the server down
    logging.warning(f"Langfuse disabled: {_e}")
    _langfuse = None


def get_text_prompt(name: str, fallback: str, **variables: object) -> str:
    if _langfuse is None:
        return fallback
    prompt = _langfuse.get_prompt(name, label="production", type="text", fallback=fallback)
    return prompt.compile(**variables)


def get_chat_messages(name: str, fallback: list[dict], **variables: object) -> list[dict]:
    """Returns compiled [{"role": ..., "content": ...}, ...] — wrap into Message() at the call site."""
    if _langfuse is None:
        return fallback
    prompt = _langfuse.get_prompt(name, label="production", type="chat", fallback=fallback)
    return prompt.compile(**variables)
