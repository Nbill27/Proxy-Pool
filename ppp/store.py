"""Penyimpanan: config, sumber, kandidat, pool, export."""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path


def _is_source_tree(path: Path) -> bool:
    """True kalau folder ini sumber proyek, bukan hasil instalasi pip."""
    if any(part in ("site-packages", "dist-packages") for part in path.parts):
        return False
    return (path / "pyproject.toml").exists() or (path / "cli.py").exists()


def _resolve_root() -> Path:
    """Lokasi data: PPP_HOME > folder proyek > ~/.ppp (kalau di-install)."""
    env = os.environ.get("PPP_HOME")
    if env:
        return Path(env).expanduser().resolve()
    local = Path(__file__).resolve().parent.parent
    if _is_source_tree(local):
        return local
    return Path.home() / ".ppp"


ROOT = _resolve_root()
ROOT.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = ROOT / "config.json"
SOURCES_FILE = ROOT / "sources.json"
CANDIDATES_FILE = ROOT / "candidates.txt"
POOL_FILE = ROOT / "proxies.json"
HISTORY_FILE = ROOT / ".ppp_history"

DEFAULT_SOURCES = {
    "raw": [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
        "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000",
        "https://proxyspace.pro/http.txt",
        "https://spys.me/proxy.txt",
    ],
    "html": [
        "https://free-proxy-list.net/",
        "https://www.sslproxies.org/",
    ],
}

DEFAULT_CONFIG = {
    "concurrency": 200,
    "timeout": 8,
    "ai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "temperature": 0.4,
        "max_tokens": 1200,
        "enabled": False,
    },
}


# ---------------------------------------------------------------- json io
def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------- config
def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    stored = _read_json(CONFIG_FILE, {})
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k == "ai" and isinstance(v, dict):
                cfg["ai"].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg: dict) -> None:
    _write_json(CONFIG_FILE, cfg)


def config_path() -> Path:
    return CONFIG_FILE


# ---------------------------------------------------------------- sumber
def load_sources() -> dict:
    data = _read_json(SOURCES_FILE, None)
    if not isinstance(data, dict) or not data.get("raw") or not data.get("html"):
        data = json.loads(json.dumps(DEFAULT_SOURCES))
        _write_json(SOURCES_FILE, data)
    data.setdefault("raw", [])
    data.setdefault("html", [])
    return data


def save_sources(data: dict) -> None:
    _write_json(SOURCES_FILE, data)


def add_source(url: str, kind: str = "raw") -> bool:
    data = load_sources()
    kind = "html" if kind == "html" else "raw"
    if url in data["raw"] or url in data["html"]:
        return False
    data[kind].append(url)
    save_sources(data)
    return True


def remove_source(url: str) -> bool:
    data = load_sources()
    before = len(data["raw"]) + len(data["html"])
    data["raw"] = [u for u in data["raw"] if u != url]
    data["html"] = [u for u in data["html"] if u != url]
    after = len(data["raw"]) + len(data["html"])
    if after == before:
        return False
    save_sources(data)
    return True


def all_sources() -> list[str]:
    data = load_sources()
    return list(data["raw"]) + list(data["html"])


# ---------------------------------------------------------------- kandidat
def _norm(entry: str) -> str:
    """Normalisasi lewat parser engine (impor lambat untuk hindari siklus)."""
    from .engine import normalize

    return normalize(entry)


def load_candidates() -> list[str]:
    if not CANDIDATES_FILE.exists():
        return []
    seen, out = set(), []
    with CANDIDATES_FILE.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            p = _norm(line)
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def save_candidates(items) -> int:
    """Tulis kandidat tanpa mengubah urutan masuk (stabil antar run)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        p = _norm(raw)
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    with CANDIDATES_FILE.open("w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return len(out)


def add_candidates(items) -> tuple[int, int]:
    """Tambahkan ke file kandidat, urutan lama dipertahankan. (total, baru)."""
    existing = load_candidates()
    seen = set(existing)
    fresh: list[str] = []
    for raw in items:
        p = _norm(raw)
        if p and p not in seen:
            seen.add(p)
            fresh.append(p)
    total = save_candidates(existing + fresh)
    return total, len(fresh)


# ---------------------------------------------------------------- pool
def load_pool() -> list[dict]:
    data = _read_json(POOL_FILE, [])
    return data if isinstance(data, list) else []


def save_pool(rows: list[dict]) -> int:
    rows = sorted(rows, key=lambda r: r.get("latency_ms", 99999))
    _write_json(POOL_FILE, rows)
    return len(rows)


def merge_pool(rows: list[dict]) -> tuple[int, int]:
    """Gabung hasil uji ke pool lama, dedup per proxy. (total, baru)."""
    old = {r["proxy"]: r for r in load_pool() if "proxy" in r}
    added = 0
    for r in rows:
        p = r.get("proxy")
        if not p:
            continue
        if p not in old:
            added += 1
        prev = old.get(p)
        # simpan yang latency-nya lebih baik
        if prev is None or r.get("latency_ms", 99999) <= prev.get("latency_ms", 99999):
            old[p] = r
    total = save_pool(list(old.values()))
    return total, added


# ---------------------------------------------------------------- export
def export_pool(fmt: str, rows: list[dict], target: Path | None = None) -> Path:
    fmt = fmt.lower()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = target or (ROOT / f"pool-{stamp}.{fmt}")

    if fmt == "json":
        _write_json(target, rows)
    elif fmt == "txt":
        target.write_text("\n".join(r["proxy"] for r in rows), encoding="utf-8")
    elif fmt == "csv":
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["proxy", "exit_ip", "scheme", "latency_ms", "anon"])
            for r in rows:
                w.writerow([r.get("proxy"), r.get("exit_ip"), r.get("scheme"),
                            r.get("latency_ms"), r.get("anon")])
    elif fmt in ("env", "sh", "bash"):
        if rows:
            lines = ["# pool siap pakai", f"export HTTP_PROXY=http://{rows[0]['proxy']}"]
            lines += [f"# alt{i}: http://{r['proxy']}" for i, r in enumerate(rows[1:20], 2)]
        else:
            lines = ["# kosong"]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"format tidak dikenal: {fmt}")

    return target


def stats() -> dict:
    pool = load_pool()
    cands = load_candidates()
    return {
        "kandidat": len(cands),
        "pool": len(pool),
        "https": sum(1 for r in pool if r.get("scheme") == "https"),
        "elite": sum(1 for r in pool if r.get("anon") == "elite"),
        "median_ms": sorted(r.get("latency_ms", 0) for r in pool)[len(pool) // 2] if pool else 0,
        "sumber": len(all_sources()),
    }
