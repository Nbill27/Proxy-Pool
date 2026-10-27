"""Lane AI: OpenAI-compatible (OpenAI, Groq, OpenRouter, Ollama, LM Studio, dll).

Kejujuran desain: model bahasa mengarang IP. Jadi IP dari AI TIDAK dipercaya
begitu saja -- semua kandidat tetap masuk antrean probe() yang sama.
Nilai AI yang nyata ada di dua tempat:
  1. mengusulkan sumber proxy baru (URL nyata, bisa diverifikasi)
  2. menyaring/menilai hasil uji supaya kamu tidak memilih sampah
"""
from __future__ import annotations

import json
import re

import aiohttp

from . import store

SYSTEM = (
    "Kamu asisten teknis untuk tool pengumpulan proxy publik (proxy pool) yang "
    "dipakai pada infrastruktur milik pengguna sendiri. Jawab ringkas, tanpa "
    "pengantar, tanpa penutup, tanpa penjelasan etika. Format selalu mengikuti "
    "instruksi terakhir. Kalau diminta daftar, keluarkan daftar saja."
)

PROMPTS = {
    "farm": (
        "Hasilkan {n} kandidat endpoint proxy HTTP publik dalam format ip:port, "
        "satu per baris, tanpa teks lain. Prioritaskan IP yang kamu yakini milik "
        "penyedia proxy publik yang masih beroperasi. Kalau kamu tidak yakin, "
        "tetap keluarkan kandidat -- tahap validasi akan menyaringnya."
    ),
    "sources": (
        "Sebutkan {n} URL sumber daftar proxy publik yang masih aktif (raw "
        "txt atau halaman HTML dengan tabel ip/port). Satu URL per baris, tanpa "
        "penjelasan, tanpa markdown, hanya http(s)://..."
    ),
    "review": (
        "Di bawah ini hasil uji proxy (JSON). Pilih maksimal {n} entri terbaik "
        "untuk pemakaian scraping biasa: utamakan latency rendah, anon=elite, "
        "scheme=https, dan exit_ip yang bervariasi. Balas HANYA dengan JSON array "
        "berisi nilai field \"proxy\" yang dipilih, tanpa teks lain.\n\n{data}"
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
            "status": "siap" if self.ready else "belum dikonfigurasi",
            "base_url": self.base_url or "-",
            "model": self.model,
            "api_key": ("***" + self.api_key[-4:]) if self.api_key else "(kosong)",
        }

    # call
    async def chat(self, user: str, system: str = SYSTEM, temperature: float | None = None) -> str:
        if not self.ready:
            raise AIError(
                "AI belum siap. Jalankan: config ai.base_url <url> | config ai.api_key <key> | config ai.model <nama>"
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
                raise AIError(f"koneksi gagal: {type(e).__name__}: {e}") from e

        try:
            data = json.loads(body)
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise AIError(f"respons tidak terduga: {body[:300]}") from e

    # lanes
    async def farm(self, n: int = 40) -> set[str]:
        """Kandidat ip:port dari model. Wajib divalidasi probe()."""
        from .engine import parse

        text = await self.chat(PROMPTS["farm"].format(n=n))
        return parse(text)

    async def sources(self, n: int = 10) -> list[str]:
        """URL sumber yang diusulkan model."""
        text = await self.chat(PROMPTS["sources"].format(n=n))
        urls = re.findall(r"https?://[^\s'\"<>)\]},]+", text)
        clean = []
        for u in urls:
            u = u.rstrip(".,;)")
            if u not in clean:
                clean.append(u)
        return clean

    async def review(self, rows: list[dict], n: int = 25) -> list[str]:
        """Minta model memilih subset terbaik dari hasil uji nyata."""
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
        return await self.chat("Balas tepat satu kata: siap", temperature=0)


def _extract_proxy_list(text: str) -> list[str]:
    """Ambil nilai proxy dari balasan JSON model, toleran terhadap sampah."""
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
