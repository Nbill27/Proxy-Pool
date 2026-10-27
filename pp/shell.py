"""Interactive REPL: a small shell to scrape, test, and manage the pool."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import aiohttp

from . import ai as ai_mod
from . import engine, store, ui

PROMPT = f"\001{ui.GREEN}\002pp\001{ui.RESET}\002{ui.GREY}>\001{ui.RESET}\002 "

HELP = [
    ("status", "summary of candidates, pool, sources, AI config"),
    ("harvest", "scrape all sources -> candidates.txt    [--timeout N]"),
    ("import", "add proxies manually: import <text> | import file <path> | import url <url>"),
    ("test", "test candidates/pool -> proxies.json    [--limit N] [--src pool|cand] [--c N]"),
    ("pool", "show pool contents    [--sort lat|ip] [--limit N]"),
    ("export", "save pool to a file    export <json|txt|csv|env> [path]"),
    ("check", "test one proxy now    check <ip:port>"),
    ("source", "manage sources    source list | source add <url> [raw|html] | source rm <url>"),
    ("ai", "AI lane    ai farm [n] | ai sources [n] | ai review [n] | ai ping | ai status"),
    ("config", "view/change config    config | config <key> <value>"),
    ("doctor", "check dependencies, connection, files"),
    ("clear", "clear the screen"),
    ("help", "command list"),
    ("exit", "quit"),
]


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


CONFIG_MAP = {
    "concurrency": ("concurrency", int),
    "timeout": ("timeout", int),
    "ai.enabled": ("ai.enabled", _bool),
    "ai.base_url": ("ai.base_url", str),
    "ai.api_key": ("ai.api_key", str),
    "ai.model": ("ai.model", str),
    "ai.temperature": ("ai.temperature", float),
    "ai.max_tokens": ("ai.max_tokens", int),
}


# ---------------------------------------------------------------- helper
def _flag(args: list[str], name: str, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _switch(args: list[str], name: str) -> bool:
    """Valueless flag, e.g. --test at the end of a line."""
    return name in args


def _pos(args: list[str], skip: int = 0) -> list[str]:
    """Positional arguments (drop anything starting with -- or a flag value)."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            # single-value flag -> skip its value
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                i += 2
                continue
            i += 1
            continue
        out.append(a)
        i += 1
    return out[skip:]


def _print_help() -> None:
    ui.label("commands")
    for cmd, desc in HELP:
        print(f"  {ui.CYAN}{cmd:<9}{ui.RESET}{ui.GREY}{desc}{ui.RESET}")
    print()
    ui.note("up/down arrows = history (if readline is available), ctrl+c = cancel, ctrl+d = quit")


# ---------------------------------------------------------------- commands
class Shell:
    def __init__(self) -> None:
        self.cfg = store.load_config()
        self.running = True
        self.last_pool: list[dict] = []

    # -------------------------------------------------------- loop
    async def run(self) -> None:
        ui.banner(f"welcome. type {ui.CYAN}help{ui.RESET} to start.")
        store.load_sources()
        while self.running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, input, PROMPT)
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            try:
                await self.dispatch(line)
            except KeyboardInterrupt:
                print()
                ui.warn("cancelled")
            except Exception as e:
                ui.err(f"{type(e).__name__}: {e}")
        ui.note("see you.")

    async def dispatch(self, line: str) -> None:
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]

        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            ui.err(f"unknown command: {cmd}")
            ui.note("type help")
            return
        result = handler(args)
        if asyncio.iscoroutine(result):
            await result

    # -------------------------------------------------------- meta
    def cmd_help(self, args):
        _print_help()

    def cmd_clear(self, args):
        ui.clear()

    def cmd_exit(self, args):
        self.running = False

    # -------------------------------------------------------- status
    def cmd_status(self, args):
        st = store.stats()
        ai = ai_mod.AI(self.cfg)
        ui.rule("status")
        ui.kv_table({
            "candidates": f"{st['candidates']} entries  ({store.CANDIDATES_FILE.name})",
            "live pool": f"{st['pool']}  (https {st['https']}, elite {st['elite']})",
            "median latency": f"{st['median_ms']} ms" if st["pool"] else "-",
            "sources": f"{st['sources']} url",
            "concurrency": self.cfg.get("concurrency"),
            "timeout": f"{self.cfg.get('timeout')} s",
            "ai": f"{ai.describe()['status']}  ({ai.model})",
        })
        pu = store.POOL_FILE.stat().st_mtime if store.POOL_FILE.exists() else 0
        if pu:
            import time

            ui.note(f"pool last saved: {time.strftime('%Y-%m-%d %H:%M', time.localtime(pu))}")
        print()

    # -------------------------------------------------------- sources
    def cmd_source(self, args):
        pos = _pos(args)
        sub = pos[0] if pos else "list"
        data = store.load_sources()

        if sub == "list":
            ui.rule("raw sources")
            for u in data["raw"]:
                print(f"  {ui.GREY}-{ui.RESET} {u}")
            ui.rule("html sources")
            for u in data["html"]:
                print(f"  {ui.GREY}-{ui.RESET} {u}")
            print()
            ui.note(f"total {len(data['raw']) + len(data['html'])} url")
            return

        if sub == "add":
            if len(pos) < 2:
                ui.err("usage: source add <url> [raw|html]")
                return
            url = pos[1]
            kind = pos[2] if len(pos) > 2 else "raw"
            if not url.startswith("http"):
                ui.err("url must be http(s)://")
                return
            if store.add_source(url, kind):
                ui.ok(f"added to {kind}: {url}")
            else:
                ui.warn("already exists")

        elif sub in ("rm", "remove", "del"):
            if len(pos) < 2:
                ui.err("usage: source rm <url>")
                return
            if store.remove_source(pos[1]):
                ui.ok(f"removed: {pos[1]}")
            else:
                ui.err("not found")
        else:
            ui.err("subcommand: list | add | rm")

    # -------------------------------------------------------- harvest
    async def cmd_harvest(self, args):
        ui.rule("harvest")
        timeout = int(_flag(args, "--timeout", self.cfg.get("timeout", 8)))
        async with engine.make_session(64) as session:
            def on_source(url, n, error):
                if error:
                    ui.err(f"{url}  {error}")
                else:
                    print(f"  {ui.GREEN}{n:>6}{ui.RESET}  {ui.GREY}{url}{ui.RESET}")

            res = await engine.harvest(session, timeout, on_source)

        cands = res["candidates"]
        if not cands:
            ui.warn("no candidates. check sources: source list")
            return

        total, new = store.add_candidates(cands)
        ui.ok(f"unique candidates: {len(cands)}, new: {new}, total file: {total}")
        ui.note(f"-> {store.CANDIDATES_FILE}")

    # -------------------------------------------------------- import
    async def cmd_import(self, args):
        pos = _pos(args)
        if not pos:
            ui.warn("usage: import <ip:port ...> | import file <path> | import url <url>")
            return

        mode = pos[0].lower()
        items: set[str] = set()

        if mode == "file":
            if len(pos) < 2:
                ui.err("usage: import file <path>")
                return
            p = Path(pos[1]).expanduser()
            if not p.exists():
                ui.err(f"file not found: {p}")
                return
            items = engine.parse_lines(p.read_text(errors="ignore"))
            ui.info(f"read from {p.name}")

        elif mode == "url":
            if len(pos) < 2:
                ui.err("usage: import url <url>")
                return
            url = pos[1]
            try:
                async with engine.make_session(8) as s:
                    async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status != 200:
                            ui.err(f"HTTP {r.status}")
                            return
                        items = engine.parse(await r.text(errors="ignore"))
            except Exception as e:
                ui.err(f"{type(e).__name__}: {e}")
                return

        elif mode == "paste":
            ui.note("paste the proxy list, finish with a single line containing a dot (.)")
            buf = []
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, input, f"{ui.GREY}..{ui.RESET} ")
                if line.strip() == ".":
                    break
                buf.append(line)
            items = engine.parse_lines("\n".join(buf))

        else:
            items = engine.parse_lines(" ".join(pos))

        if not items:
            ui.warn("no valid ip:port entries")
            return

        total, new = store.add_candidates(items)
        ui.ok(f"valid: {len(items)}, new: {new}, total file: {total}")
        ui.note("next: test --src cand --limit N")

    # -------------------------------------------------------- test
    async def cmd_test(self, args, only: list[str] | None = None):
        limit = int(_flag(args, "--limit", 0))
        conc = int(_flag(args, "--c", _flag(args, "-c", _flag(args, "--concurrency", self.cfg.get("concurrency", 200)))))
        timeout = int(_flag(args, "--timeout", self.cfg.get("timeout", 8)))
        src = _flag(args, "--src", "cand")

        if only is not None:
            cands = list(dict.fromkeys(only))
            label = "AI candidates"
        elif src == "pool":
            pool = store.load_pool()
            cands = [r["proxy"] for r in pool]
            label = "pool"
        else:
            cands = store.load_candidates()
            label = "candidates"

        if not cands:
            ui.warn(f"{label} is empty. run harvest or import first")
            return

        targets = cands if only is not None else engine.sample(cands, limit)
        ui.rule(f"testing {len(targets)} {label}  concurrency {conc}  timeout {timeout}s")

        bar = ui.Bar(len(targets), prefix="test")

        def on_progress(done, total, alive):
            bar.update(done, extra=f"alive {alive}")

        res = await engine.test_many(targets, conc, timeout, on_progress)
        bar.update(len(targets), extra=f"alive {len(res['alive'])}", force=True)

        alive = res["alive"]
        if not alive:
            ui.warn(f"nothing alive (your IP: {res['my_ip'] or '?'})")
            return

        total_pool, added = store.merge_pool(alive)
        s = engine.summarize(alive)
        ui.ok(
            f"alive {s['alive']}/{len(targets)}  https {s['https']}  elite {s['elite']}  "
            f"median {s['median_ms']}ms  ({res['elapsed']}s)"
        )
        ui.note(f"fastest: {s['fastest']}")
        ui.note(f"pool: +{added} new -> {total_pool} total  ({store.POOL_FILE.name})")

    # -------------------------------------------------------- pool
    def cmd_pool(self, args):
        rows = store.load_pool()
        if not rows:
            ui.warn("pool is empty. run test first")
            return
        limit = int(_flag(args, "--limit", 40))
        if _flag(args, "--sort", "lat") == "ip":
            rows = sorted(rows, key=lambda r: r.get("proxy", ""))

        ui.rule(f"pool ({len(rows)} entries)")
        ui.table(
            ["#", "proxy", "exit", "scheme", "ms", "anon"],
            [[str(i + 1), r["proxy"], r.get("exit_ip", "-"), r.get("scheme", "-"),
              str(r.get("latency_ms", "-")), r.get("anon", "-")] for i, r in enumerate(rows)],
            colorize=None,
            max_rows=limit,
        )
        print()
        ui.note("export <json|txt|csv|env> to save a copy")

    # -------------------------------------------------------- export
    def cmd_export(self, args):
        pos = _pos(args)
        fmt = pos[0].lower() if pos else "txt"
        rows = store.load_pool()
        if not rows:
            ui.warn("pool is empty, nothing to export")
            return
        target = Path(pos[1]) if len(pos) > 1 else None
        try:
            p = store.export_pool(fmt, rows, target)
        except ValueError as e:
            ui.err(str(e))
            return
        ui.ok(f"{len(rows)} entries -> {p}")

    # -------------------------------------------------------- check
    async def cmd_check(self, args):
        pos = _pos(args)
        if not pos:
            ui.err("usage: check <ip:port>")
            return
        proxy = pos[0]
        if not engine.parse(proxy):
            ui.err(f"invalid format: {proxy}")
            return
        ui.info(f"testing {proxy} ...")
        timeout = int(_flag(args, "--timeout", self.cfg.get("timeout", 8)))
        sem = asyncio.Semaphore(1)
        async with engine.make_session(8) as session:
            my_ip = await engine.real_ip(session)
            res = await engine.probe(session, proxy, sem, my_ip, timeout)
        if not res:
            ui.warn(f"dead or transparent (your IP {my_ip or '?'})")
            return
        ui.ok("alive")
        ui.kv_table(res)

    # -------------------------------------------------------- ai
    async def cmd_ai(self, args):
        pos = _pos(args)
        sub = pos[0] if pos else "status"
        ai = ai_mod.AI(self.cfg)

        if sub in ("status", "info"):
            ui.rule("ai")
            ui.kv_table(ai.describe())
            print()
            if not ai.ready:
                ui.note("fix: config ai.base_url <url> / config ai.api_key <key> / config ai.model <name>")
            ui.note("local example: config ai.base_url http://localhost:11434/v1  +  config ai.model llama3.1")
            return

        if sub == "ping":
            try:
                reply = await ai.ping()
                ui.ok(f"model replied: {reply.strip()[:80]}")
            except ai_mod.AIError as e:
                ui.err(str(e))
            return

        if not ai.ready:
            ui.err("AI is not configured. run: ai status")
            return

        if sub == "farm":
            n = int(pos[1]) if len(pos) > 1 else 40
            ui.info(f"requesting {n} candidates from {ai.model} ...")
            try:
                cands = await ai.farm(n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not cands:
                ui.warn("the model returned no parsable ip:port")
                return
            total, new = store.add_candidates(cands)
            ui.ok(f"AI candidates: {len(cands)}, new: {new}, total file: {total}")
            ui.note("model IPs are often invented. validation required: test --src cand --limit N")
            if _switch(args, "--test"):
                await self.cmd_test([], only=sorted(cands))
            return

        if sub in ("sources", "src"):
            n = int(pos[1]) if len(pos) > 1 else 10
            ui.info("requesting source suggestions ...")
            try:
                urls = await ai.sources(n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not urls:
                ui.warn("no parsable URL")
                return
            ui.label("source suggestions")
            for u in urls:
                print(f"  {ui.CYAN}{u}{ui.RESET}")
            print()
            ui.note("add the sensible ones: source add <url> raw")
            return

        if sub == "review":
            rows = store.load_pool()
            if not rows:
                ui.warn("pool is empty, nothing to review")
                return
            n = int(pos[1]) if len(pos) > 1 else 25
            ui.info(f"asking {ai.model} to pick {n} best of {len(rows)} ...")
            try:
                chosen = await ai.review(rows, n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not chosen:
                ui.warn("the model picked nothing")
                return
            ui.ok(f"picked {len(chosen)}")
            ui.table(["proxy"], [[p] for p in chosen], max_rows=40)
            print()
            ui.note("export txt to save the selection")
            return

        ui.err("subcommand: status | ping | farm | sources | review")

    # -------------------------------------------------------- config
    def cmd_config(self, args):
        pos = _pos(args)
        cfg = store.load_config()

        if not pos:
            ui.rule("config")
            flat = {
                "concurrency": cfg.get("concurrency"),
                "timeout": cfg.get("timeout"),
            }
            for k, v in cfg.get("ai", {}).items():
                flat[f"ai.{k}"] = ("***" + str(v)[-4:]) if k == "api_key" and v else v
            ui.kv_table(flat, key_w=20)
            print()
            ui.note(f"file: {store.config_path()}")
            ui.note("change: config <key> <value>   (example: config timeout 12)")
            return

        key = pos[0]
        if key not in CONFIG_MAP:
            ui.err(f"unknown key: {key}")
            ui.note("options: " + ", ".join(CONFIG_MAP))
            return

        if len(pos) < 2:
            value = cfg
            for part in CONFIG_MAP[key][0].split("."):
                value = value.get(part) if isinstance(value, dict) else None
            shown = ("***" + str(value)[-4:]) if key == "ai.api_key" and value else value
            print(f"  {key} = {shown}")
            return

        raw = " ".join(pos[1:])
        path, caster = CONFIG_MAP[key]
        if raw.strip() in ("-", "empty", "clear", "unset"):
            raw = ""
        try:
            value = caster(raw)
        except ValueError:
            ui.err(f"invalid value for {key}: {raw}")
            return

        node = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

        if path.startswith("ai.") and value and path != "ai.enabled":
            cfg.setdefault("ai", {})["enabled"] = True

        store.save_config(cfg)
        self.cfg = cfg
        shown = ("***" + str(value)[-4:]) if key == "ai.api_key" else value
        ui.ok(f"{key} = {shown}")

    # -------------------------------------------------------- doctor
    async def cmd_doctor(self, args):
        ui.rule("doctor")
        checks = []

        checks.append(("python", True, f"{__import__('sys').version.split()[0]}"))

        try:
            import aiohttp

            checks.append(("aiohttp", True, aiohttp.__version__))
        except Exception as e:
            checks.append(("aiohttp", False, str(e)))

        checks.append(("config.json", store.CONFIG_FILE.exists(), str(store.CONFIG_FILE)))
        checks.append(("sources.json", store.SOURCES_FILE.exists(), f"{len(store.all_sources())} url"))
        checks.append(("candidates.txt", store.CANDIDATES_FILE.exists(), f"{len(store.load_candidates())} entries"))
        checks.append(("proxies.json", store.POOL_FILE.exists(), f"{len(store.load_pool())} entries"))

        ai = ai_mod.AI(self.cfg)
        checks.append(("ai", ai.ready, ai.model if ai.ready else "not configured"))

        # outbound connection
        try:
            async with engine.make_session(4) as s:
                ip = await engine.real_ip(s)
            checks.append(("connection", bool(ip), f"public IP {ip or '?'}"))
        except Exception as e:
            checks.append(("connection", False, type(e).__name__))

        for name, good, detail in checks:
            mark = f"{ui.GREEN}ok{ui.RESET}  " if good else f"{ui.RED}fail{ui.RESET}"
            print(f"  {mark} {ui.BOLD}{name:<14}{ui.RESET} {ui.GREY}{detail}{ui.RESET}")
        print()

        bad = [c for c in checks if not c[1]]
        if bad:
            ui.warn(f"{len(bad)} problems. fix the failing ones first.")
        else:
            ui.ok("all healthy.")
