#!/usr/bin/env python3
"""Оператор как чистая LLM: OpenAI-compatible chat completions, без инструментов.

Оператор видит только сообщения исполнителя, список файлов и текст проверок.
Файлы сам не читает.
"""
from __future__ import annotations

import json
import os
import urllib.request

BASE = os.environ.get("OPERATOR_BASE_URL", "http://127.0.0.1:18080/v1")
MODEL = os.environ.get("OPERATOR_MODEL", "deepseek-v4.1-flash-1017-uncensored")
KEY = os.environ.get("OPERATOR_API_KEY", "not-needed")


def ask(messages: list[dict], timeout: float = 600) -> dict:
    body = json.dumps({
        "model": MODEL, "messages": messages, "temperature": 0.3,
        "chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"},
    }).encode()
    req = urllib.request.Request(
        BASE.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"text": "", "error": str(e), "usage": None}
    ch = (d.get("choices") or [{}])[0].get("message") or {}
    return {"text": (ch.get("content") or "").strip(), "usage": d.get("usage"), "error": None}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("system")
    ap.add_argument("prompt")
    a = ap.parse_args()
    print(json.dumps(ask([{"role": "system", "content": a.system}, {"role": "user", "content": a.prompt}]), ensure_ascii=False, indent=1))
