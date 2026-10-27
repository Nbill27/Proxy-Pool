"""AI lane: OpenAI-compatible (OpenAI, Groq, OpenRouter, Ollama, LM Studio, etc.).

Design honesty: language models invent IPs. So IPs coming from the AI are not
trusted as-is -- every candidate still enters the same probe() queue.
The real value of the AI lane sits in two places:
  1. proposing new proxy sources (real URLs, verifiable)
  2. filtering/ranking real test results so you do not pick junk
"""
from __future__ import annotations

import json
import re

import aiohttp

from . import store

SYSTEM = (
    "You are a technical assistant for a public proxy collection tool (proxy pool) "
    "used on the user's own infrastructure. Answer concisely, with no preamble, no "
    "closing, and no ethics lecture. Always follow the format of the last "
    "instruction. If asked for a list, output the list only."
)

PROMPTS = {
    "farm": (
        "Produce {n} public HTTP proxy endpoint candidates in ip:port format, "
        "one per line, with no other text. Prioritize IPs you believe belong to "
        "public proxy providers that are still operating. If you are unsure, "
        "still emit candidates -- the validation stage will filter them."
    ),
    "sources": (
        "List {n} URLs of public proxy list sources that are still active (raw "
        "txt or HTML pages with an ip/port table). One URL per line, no "
        "explanation, no markdown, only http(s)://..."
    ),
    "review": (
        "Below are proxy test results (JSON). Pick at most {n} best entries for "
        "ordinary scraping use: prefer low latency, anon=elite, scheme=https, and "
        "varied exit_ip. Reply ONLY with a JSON array containing the chosen "
        "\"proxy\" field values, with no other text.\n\n{data}"
    ),
}


class AIError(RuntimeError):
    pass


class AI:
    def __init__(self, cfg: dict | None = None):
        self.cfg = (cfg or store.load_config()).get("ai", {})
        self.base_url = (self.cfg.get("base_url") or "").rstrip("/")
        self.api_key = self.cfg.get("api_key") or ""
        self.model = self.cfg.get("model") or "gpt-4o-mini"

    # status
    @property
    def ready(self) -> bool:
        if not self.base_url:
            return False
        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            return False
        return True

    def describe(self) -> dict:
        return {
            "status": "ready" if self.ready else "not configured",
            "base_url": self.base_url or "-",
            "model": self.model,
            "api_key": ("***" + self.api_key[-4:]) if self.api_key else "(empty)",
        }

    # call
    async def chat(self, user: str, system: str = SYSTEM, temperature: float | None = None) -> str:
        if not self.ready:
            raise AIError(
                "AI is not ready. Run: config ai.base_url <url> | config ai.api_key <key> | config ai.model <name>"
            )

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.get("temperature", 0.4) if temperature is None else temperature,
            "max_tokens": self.cfg.get("max_tokens", 1200),
            "stream": False,
        }

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            try:
                async with s.post(url, json=payload, headers=headers) as r:
                    body = await r.text()
                    if r.status != 200:
                        raise AIError(f"HTTP {r.status}: {body[:300]}")
            except aiohttp.ClientError as e:
                raise AIError(f"connection failed: {type(e).__name__}: {e}") from e

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise AIError(f"unexpected response: {body[:300]}") from e

    # lanes
    async def farm(self, n: int = 40) -> set[str]:
        """Candidate ip:port from the model. Must be validated by probe()."""
        from .engine import parse

        text = await self.chat(PROMPTS["farm"].format(n=n))
        return parse(text)

    async def sources(self, n: int = 10) -> list[str]:
        """Source URLs proposed by the model."""
        text = await self.chat(PROMPTS["sources"].format(n=n))
        urls = re.findall(r"https?://[^\s'\"<>)\]},]+", text)
        clean = []
        for u in urls:
            u = u.rstrip(".,;)")
            if u not in clean:
                clean.append(u)
        return clean

    async def review(self, rows: list[dict], n: int = 25) -> list[str]:
        """Ask the model to pick the best subset of real test results."""
        trimmed = [
            {k: r.get(k) for k in ("proxy", "exit_ip", "scheme", "latency_ms", "anon")}
            for r in rows[:200]
        ]
        text = await self.chat(
            PROMPTS["review"].format(n=n, data=json.dumps(trimmed, ensure_ascii=False)),
            temperature=0.1,
        )
        chosen = _extract_proxy_list(text)
        known = {r["proxy"] for r in rows}
        return [p for p in chosen if p in known]

    async def ping(self) -> str:
        return await self.chat("Reply with exactly one word: ready", temperature=0)


def _extract_proxy_list(text: str) -> list[str]:
    """Extract proxy values from the model reply, tolerant of junk."""
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            data = json.loads(m.group(0))
            out = []
            for item in data:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, dict):
                    v = item.get("proxy") or item.get("ip_port")
                    if isinstance(v, str):
                        out.append(v)
            if out:
                return out
        except Exception:
            pass
    return re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b", text)
