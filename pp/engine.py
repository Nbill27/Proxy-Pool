"""Core: parse, harvest, real_ip, probe, bulk testing."""
from __future__ import annotations

import asyncio
import random
import re
import time

import aiohttp

from . import store

IP_CHECK = "https://api.ipify.org"
TEST_URL = "https://httpbin.org/anything"

IP_PORT_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})\b")
ROW_RE = re.compile(
    r"<td[^>]*>\s*((?:\d{1,3}\.){3}\d{1,3})\s*</td>\s*<td[^>]*>\s*(\d{2,5})\s*</td>",
    re.I | re.S,
)
# "1.2.3.4 8080", "1.2.3.4:8080", or "1.2.3.4,8080"
LOOSE_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\s*[:\s,;|]\s*(\d{2,5})\b")
# "http://", "socks5://", ...
SCHEME_RE = re.compile(r"^\s*[a-z][a-z0-9+.\-]*://", re.I)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) pp/2.0"}


# parse
def _valid(ip: str, port: str) -> bool:
    try:
        octets = [int(o) for o in ip.split(".")]
    except ValueError:
        return False
    if len(octets) != 4 or any(o < 0 or o > 255 for o in octets):
        return False
    if octets[0] in (0, 10, 127) or octets[0] >= 224:
        return False
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return False
    if octets[0] == 192 and octets[1] == 168:
        return False
    if octets[0] == 100 and 64 <= octets[1] <= 127:  # CGNAT 100.64/10
        return False
    if octets[0] == 169 and octets[1] == 254:  # link-local 169.254/16
        return False
    if octets[0] == 198 and octets[1] in (18, 19):  # benchmark 198.18/15
        return False
    try:
        p = int(port)
    except ValueError:
        return False
    return 0 < p < 65536


def parse(text: str) -> set[str]:
    """Pull ip:port pairs out of HTML tables, raw text, or mixed lists."""
    found = {f"{ip}:{port}" for ip, port in ROW_RE.findall(text)}
    found |= {f"{ip}:{port}" for ip, port in IP_PORT_RE.findall(text)}
    found |= {f"{ip}:{port}" for ip, port in LOOSE_RE.findall(text)}
    good = set()
    for p in found:
        ip, port = p.rsplit(":", 1)
        if _valid(ip, port):
            good.add(p)
    return good


def parse_lines(text: str) -> set[str]:
    """Parse manual input: one entry per line, tolerant."""
    out = set()
    for line in text.replace(",", "\n").replace(";", "\n").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out |= parse(line)
    return out


def normalize(entry: str) -> str:
    """Clean a single entry into ip:port; "" if invalid.

    Accepts `http://1.2.3.4:8080`, `1.2.3.4 8080`, `1.2.3.4:8080/`, and drops
    schemes, paths, and private/reserved entries.
    """
    s = SCHEME_RE.sub("", (entry or "").strip())
    found = parse(s.split("/")[0])
    return min(found) if found else ""


# ---------------------------------------------------------------- session
def quiet_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Silence Windows Proactor noise: a proxy drops the connection -> WinError 10054.

    The `_call_connection_lost` callback still tries to shut down an already dead
    socket, and asyncio prints a traceback. That is not a probe failure -- other
    errors are still reported as-is.
    """
    previous = loop.get_exception_handler()

    def handler(loop, context):
        if isinstance(context.get("exception"), (ConnectionResetError, ConnectionAbortedError)):
            return
        if previous is not None:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def make_session(concurrency: int) -> aiohttp.ClientSession:
    conn = aiohttp.TCPConnector(limit=concurrency, limit_per_host=0, ssl=False)
    return aiohttp.ClientSession(connector=conn, headers=HEADERS)


# ---------------------------------------------------------------- harvest
async def harvest(session: aiohttp.ClientSession, timeout: int, on_source=None) -> dict:
    """Scrape every source. Returns {'candidates': set, 'report': [...]}"""
    urls = store.all_sources()
    candidates: set[str] = set()
    report = []

    async def fetch(url):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return url, set(), f"HTTP {r.status}", 0
                body = await r.text(errors="ignore")
                items = parse(body)
                return url, items, None, len(items)
        except Exception as e:
            return url, set(), type(e).__name__, 0

    results = await asyncio.gather(*(fetch(u) for u in urls))
    for url, items, error, n in results:
        candidates |= items
        report.append({"url": url, "count": n, "error": error})
        if on_source:
            on_source(url, n, error)

    return {"candidates": candidates, "report": report}


# probe
async def real_ip(session: aiohttp.ClientSession) -> str:
    for url in (IP_CHECK, "http://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                txt = (await r.text()).strip().split("\n")[0]
                if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", txt):
                    return txt
        except Exception:
            continue
    return ""


async def probe(session, proxy: str, sem: asyncio.Semaphore, my_ip: str, timeout: int):
    """One request attempt through a proxy. None if dead or transparent."""
    async with sem:
        for scheme, test_url in (("https", TEST_URL), ("http", "http://httpbin.org/anything")):
            t0 = time.perf_counter()
            try:
                async with session.get(
                    test_url,
                    proxy=f"http://{proxy}",
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as r:
                    if r.status != 200:
                        continue
                    data = await r.json(content_type=None)
            except Exception:
                continue

            if not isinstance(data, dict):
                continue
            exit_ip = str(data.get("origin", "")).split(",")[0].strip()
            if not exit_ip or exit_ip == my_ip:
                return None  # transparent: the real IP leaks through

            headers = {k.lower() for k in data.get("headers", {})}
            leaks = bool(headers & {"x-forwarded-for", "x-real-ip", "via", "forwarded"})
            return {
                "proxy": proxy,
                "exit_ip": exit_ip,
                "scheme": scheme,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "anon": "anonymous" if leaks else "elite",
            }
    return None


# bulk test
async def test_many(
    proxies: list[str],
    concurrency: int = 200,
    timeout: int = 8,
    on_progress=None,
) -> dict:
    """Test many proxies. Returns {'alive', 'dead', 'my_ip', 'elapsed'}."""
    proxies = list(dict.fromkeys(proxies))
    sem = asyncio.Semaphore(concurrency)
    alive: list[dict] = []
    dead = 0
    done = 0
    t_start = time.perf_counter()

    async with make_session(concurrency) as session:
        my_ip = await real_ip(session)

        async def worker(p):
            nonlocal dead, done
            res = await probe(session, p, sem, my_ip, timeout)
            done += 1
            if res:
                alive.append(res)
            else:
                dead += 1
            if on_progress:
                on_progress(done, len(proxies), len(alive))

        await asyncio.gather(*(worker(p) for p in proxies))

    alive.sort(key=lambda x: x["latency_ms"])
    return {
        "alive": alive,
        "dead": dead,
        "my_ip": my_ip,
        "elapsed": round(time.perf_counter() - t_start, 1),
        "tested": done,
    }


def summarize(alive: list[dict]) -> dict:
    if not alive:
        return {"alive": 0, "https": 0, "elite": 0, "median_ms": 0, "fastest": "-"}
    return {
        "alive": len(alive),
        "https": sum(1 for a in alive if a["scheme"] == "https"),
        "elite": sum(1 for a in alive if a["anon"] == "elite"),
        "median_ms": alive[len(alive) // 2]["latency_ms"],
        "fastest": f"{alive[0]['proxy']} ({alive[0]['latency_ms']}ms)",
    }


def sample(items: list[str], limit: int) -> list[str]:
    if limit and limit > 0 and len(items) > limit:
        return random.sample(items, limit)
    return list(items)
