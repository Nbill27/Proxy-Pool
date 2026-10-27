"""REPL interaktif: shell kecil untuk scrape, uji, dan kelola pool."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

import aiohttp

from . import ai as ai_mod
from . import engine, store, ui

PROMPT = f"\001{ui.GREEN}\002ppp\001{ui.RESET}\002{ui.GREY}>\001{ui.RESET}\002 "

HELP = [
    ("status", "ringkasan kandidat, pool, sumber, config AI"),
    ("harvest", "scrape semua sumber -> candidates.txt    [--timeout N]"),
    ("import", "masukkan proxy manual: import <teks> | import file <path> | import url <url>"),
    ("test", "uji kandidat/pool -> proxies.json    [--limit N] [--src pool|cand] [--c N]"),
    ("pool", "lihat isi pool    [--sort lat|ip] [--limit N]"),
    ("export", "simpan pool ke file    export <json|txt|csv|env> [path]"),
    ("check", "uji satu proxy sekarang    check <ip:port>"),
    ("source", "kelola sumber    source list | source add <url> [raw|html] | source rm <url>"),
    ("ai", "lane AI    ai farm [n] | ai sources [n] | ai review [n] | ai ping | ai status"),
    ("config", "lihat/ubah config    config | config <key> <value>"),
    ("doctor", "cek dependensi, koneksi, file"),
    ("clear", "bersihkan layar"),
    ("help", "daftar perintah"),
    ("exit", "keluar"),
]

def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on", "siap", "nyala")


KONFIG_MAP = {
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
    """Flag tanpa nilai, mis. --test di akhir baris."""
    return name in args


def _pos(args: list[str], skip: int = 0) -> list[str]:
    """Argumen posisional (buang yang berawalan -- atau nilai flag)."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            # flag bernilai tunggal -> lewati nilainya
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                i += 2
                continue
            i += 1
            continue
        out.append(a)
        i += 1
    return out[skip:]


def _print_help() -> None:
    ui.label("perintah")
    for cmd, desc in HELP:
        print(f"  {ui.CYAN}{cmd:<9}{ui.RESET}{ui.GREY}{desc}{ui.RESET}")
    print()
    ui.note("panah atas/bawah = riwayat (kalau readline tersedia), ctrl+c = batal, ctrl+d = keluar")


# ---------------------------------------------------------------- perintah
class Shell:
    def __init__(self) -> None:
        self.cfg = store.load_config()
        self.running = True
        self.last_pool: list[dict] = []

    # -------------------------------------------------------- loop
    async def run(self) -> None:
        ui.banner(f"selamat datang. ketik {ui.CYAN}help{ui.RESET} untuk mulai.")
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
                ui.warn("dibatalkan")
            except Exception as e:
                ui.err(f"{type(e).__name__}: {e}")
        ui.note("sampai jumpa.")

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
            ui.err(f"perintah tidak dikenal: {cmd}")
            ui.note("ketik help")
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
            "kandidat": f"{st['kandidat']} entri  ({store.CANDIDATES_FILE.name})",
            "pool hidup": f"{st['pool']}  (https {st['https']}, elite {st['elite']})",
            "median latency": f"{st['median_ms']} ms" if st["pool"] else "-",
            "sumber": f"{st['sumber']} url",
            "concurrency": self.cfg.get("concurrency"),
            "timeout": f"{self.cfg.get('timeout')} s",
            "ai": f"{ai.describe()['status']}  ({ai.model})",
        })
        pu = store.POOL_FILE.stat().st_mtime if store.POOL_FILE.exists() else 0
        if pu:
            import time

            ui.note(f"pool terakhir disimpan: {time.strftime('%Y-%m-%d %H:%M', time.localtime(pu))}")
        print()

    # -------------------------------------------------------- sumber
    def cmd_source(self, args):
        pos = _pos(args)
        sub = pos[0] if pos else "list"
        data = store.load_sources()

        if sub == "list":
            ui.rule("sumber raw")
            for u in data["raw"]:
                print(f"  {ui.GREY}-{ui.RESET} {u}")
            ui.rule("sumber html")
            for u in data["html"]:
                print(f"  {ui.GREY}-{ui.RESET} {u}")
            print()
            ui.note(f"total {len(data['raw']) + len(data['html'])} url")
            return

        if sub == "add":
            if len(pos) < 2:
                ui.err("pakai: source add <url> [raw|html]")
                return
            url = pos[1]
            kind = pos[2] if len(pos) > 2 else "raw"
            if not url.startswith("http"):
                ui.err("url harus http(s)://")
                return
            if store.add_source(url, kind):
                ui.ok(f"ditambahkan ke {kind}: {url}")
            else:
                ui.warn("sudah ada")

        elif sub in ("rm", "remove", "del"):
            if len(pos) < 2:
                ui.err("pakai: source rm <url>")
                return
            if store.remove_source(pos[1]):
                ui.ok(f"dihapus: {pos[1]}")
            else:
                ui.err("tidak ditemukan")
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
            ui.warn("tidak ada kandidat. cek sumber: source list")
            return

        total, new = store.add_candidates(cands)
        ui.ok(f"kandidat unik: {len(cands)}, baru: {new}, total file: {total}")
        ui.note(f"-> {store.CANDIDATES_FILE}")

    # -------------------------------------------------------- import
    async def cmd_import(self, args):
        pos = _pos(args)
        if not pos:
            ui.warn("pakai: import <ip:port ...> | import file <path> | import url <url>")
            return

        mode = pos[0].lower()
        items: set[str] = set()

        if mode == "file":
            if len(pos) < 2:
                ui.err("pakai: import file <path>")
                return
            p = Path(pos[1]).expanduser()
            if not p.exists():
                ui.err(f"file tidak ada: {p}")
                return
            items = engine.parse_lines(p.read_text(errors="ignore"))
            ui.info(f"dibaca dari {p.name}")

        elif mode == "url":
            if len(pos) < 2:
                ui.err("pakai: import url <url>")
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
            ui.note("tempel daftar proxy, akhiri dengan satu baris berisi titik (.)")
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
            ui.warn("tidak ada entri ip:port yang valid")
            return

        total, new = store.add_candidates(items)
        ui.ok(f"valid: {len(items)}, baru: {new}, total file: {total}")
        ui.note("lanjut: test --src cand --limit N")

    # -------------------------------------------------------- test
    async def cmd_test(self, args, only: list[str] | None = None):
        limit = int(_flag(args, "--limit", 0))
        conc = int(_flag(args, "--c", _flag(args, "-c", _flag(args, "--concurrency", self.cfg.get("concurrency", 200)))))
        timeout = int(_flag(args, "--timeout", self.cfg.get("timeout", 8)))
        src = _flag(args, "--src", "cand")

        if only is not None:
            cands = list(dict.fromkeys(only))
            label = "kandidat AI"
        elif src == "pool":
            pool = store.load_pool()
            cands = [r["proxy"] for r in pool]
            label = "pool"
        else:
            cands = store.load_candidates()
            label = "kandidat"

        if not cands:
            ui.warn(f"{label} kosong. jalankan harvest atau import dulu")
            return

        targets = cands if only is not None else engine.sample(cands, limit)
        ui.rule(f"uji {len(targets)} {label}  concurrency {conc}  timeout {timeout}s")

        bar = ui.Bar(len(targets), prefix="uji")

        def on_progress(done, total, alive):
            bar.update(done, extra=f"hidup {alive}")

        res = await engine.test_many(targets, conc, timeout, on_progress)
        bar.update(len(targets), extra=f"hidup {len(res['alive'])}", force=True)

        alive = res["alive"]
        if not alive:
            ui.warn(f"tidak ada yang hidup (IP kamu: {res['my_ip'] or '?'})")
            return

        total_pool, added = store.merge_pool(alive)
        s = engine.summarize(alive)
        ui.ok(
            f"hidup {s['hidup']}/{len(targets)}  https {s['https']}  elite {s['elite']}  "
            f"median {s['median_ms']}ms  ({res['elapsed']}s)"
        )
        ui.note(f"tercepat: {s['tercepat']}")
        ui.note(f"pool: +{added} baru -> {total_pool} total  ({store.POOL_FILE.name})")

    # -------------------------------------------------------- pool
    def cmd_pool(self, args):
        rows = store.load_pool()
        if not rows:
            ui.warn("pool kosong. jalankan test dulu")
            return
        limit = int(_flag(args, "--limit", 40))
        if _flag(args, "--sort", "lat") == "ip":
            rows = sorted(rows, key=lambda r: r.get("proxy", ""))

        ui.rule(f"pool ({len(rows)} entri)")
        ui.table(
            ["#", "proxy", "exit", "scheme", "ms", "anon"],
            [[str(i + 1), r["proxy"], r.get("exit_ip", "-"), r.get("scheme", "-"),
              str(r.get("latency_ms", "-")), r.get("anon", "-")] for i, r in enumerate(rows)],
            colorize=None,
            max_rows=limit,
        )
        print()
        ui.note("export <json|txt|csv|env> untuk menyimpan salinan")

    # -------------------------------------------------------- export
    def cmd_export(self, args):
        pos = _pos(args)
        fmt = pos[0].lower() if pos else "txt"
        rows = store.load_pool()
        if not rows:
            ui.warn("pool kosong, tidak ada yang diexport")
            return
        target = Path(pos[1]) if len(pos) > 1 else None
        try:
            p = store.export_pool(fmt, rows, target)
        except ValueError as e:
            ui.err(str(e))
            return
        ui.ok(f"{len(rows)} entri -> {p}")

    # -------------------------------------------------------- check
    async def cmd_check(self, args):
        pos = _pos(args)
        if not pos:
            ui.err("pakai: check <ip:port>")
            return
        proxy = pos[0]
        if not engine.parse(proxy):
            ui.err(f"format tidak valid: {proxy}")
            return
        ui.info(f"menguji {proxy} ...")
        timeout = int(_flag(args, "--timeout", self.cfg.get("timeout", 8)))
        sem = asyncio.Semaphore(1)
        async with engine.make_session(8) as session:
            my_ip = await engine.real_ip(session)
            res = await engine.probe(session, proxy, sem, my_ip, timeout)
        if not res:
            ui.warn(f"mati atau transparan (IP kamu {my_ip or '?'})")
            return
        ui.ok("hidup")
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
                ui.note("atasi: config ai.base_url <url> / config ai.api_key <key> / config ai.model <nama>")
            ui.note("contoh lokal: config ai.base_url http://localhost:11434/v1  +  config ai.model llama3.1")
            return

        if sub == "ping":
            try:
                reply = await ai.ping()
                ui.ok(f"model menjawab: {reply.strip()[:80]}")
            except ai_mod.AIError as e:
                ui.err(str(e))
            return

        if not ai.ready:
            ui.err("AI belum dikonfigurasi. jalankan: ai status")
            return

        if sub == "farm":
            n = int(pos[1]) if len(pos) > 1 else 40
            ui.info(f"minta {n} kandidat dari {ai.model} ...")
            try:
                cands = await ai.farm(n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not cands:
                ui.warn("model tidak mengembalikan ip:port yang bisa diparse")
                return
            total, new = store.add_candidates(cands)
            ui.ok(f"kandidat AI: {len(cands)}, baru: {new}, total file: {total}")
            ui.note("IP dari model sering karangan. validasi wajib: test --src cand --limit N")
            if _switch(args, "--test"):
                await self.cmd_test([], only=sorted(cands))
            return

        if sub in ("sources", "src"):
            n = int(pos[1]) if len(pos) > 1 else 10
            ui.info("minta usulan sumber ...")
            try:
                urls = await ai.sources(n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not urls:
                ui.warn("tidak ada URL yang bisa diparse")
                return
            ui.label("usulan sumber")
            for u in urls:
                print(f"  {ui.CYAN}{u}{ui.RESET}")
            print()
            ui.note("tambah yang masuk akal: source add <url> raw")
            return

        if sub == "review":
            rows = store.load_pool()
            if not rows:
                ui.warn("pool kosong, tidak ada yang bisa direview")
                return
            n = int(pos[1]) if len(pos) > 1 else 25
            ui.info(f"minta {ai.model} memilih {n} terbaik dari {len(rows)} ...")
            try:
                chosen = await ai.review(rows, n)
            except ai_mod.AIError as e:
                ui.err(str(e))
                return
            if not chosen:
                ui.warn("model tidak memilih apa pun")
                return
            ui.ok(f"dipilih {len(chosen)}")
            ui.table(["proxy"], [[p] for p in chosen], max_rows=40)
            print()
            ui.note("export txt untuk menyimpan hasil terpilih")
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
            ui.note("ubah: config <key> <value>   (contoh: config timeout 12)")
            return

        key = pos[0]
        if key not in KONFIG_MAP:
            ui.err(f"key tidak dikenal: {key}")
            ui.note("pilihan: " + ", ".join(KONFIG_MAP))
            return

        if len(pos) < 2:
            value = cfg
            for part in KONFIG_MAP[key][0].split("."):
                value = value.get(part) if isinstance(value, dict) else None
            shown = ("***" + str(value)[-4:]) if key == "ai.api_key" and value else value
            print(f"  {key} = {shown}")
            return

        raw = " ".join(pos[1:])
        path, caster = KONFIG_MAP[key]
        if raw.strip() in ("-", "kosong", "clear", "hapus"):
            raw = ""
        try:
            value = caster(raw)
        except ValueError:
            ui.err(f"nilai tidak valid untuk {key}: {raw}")
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
        checks.append(("candidates.txt", store.CANDIDATES_FILE.exists(), f"{len(store.load_candidates())} entri"))
        checks.append(("proxies.json", store.POOL_FILE.exists(), f"{len(store.load_pool())} entri"))

        ai = ai_mod.AI(self.cfg)
        checks.append(("ai", ai.ready, ai.model if ai.ready else "belum dikonfigurasi"))

        # koneksi keluar
        try:
            async with engine.make_session(4) as s:
                ip = await engine.real_ip(s)
            checks.append(("koneksi", bool(ip), f"IP publik {ip or '?'}"))
        except Exception as e:
            checks.append(("koneksi", False, type(e).__name__))

        for name, good, detail in checks:
            mark = f"{ui.GREEN}ok{ui.RESET}  " if good else f"{ui.RED}gagal{ui.RESET}"
            print(f"  {mark} {ui.BOLD}{name:<14}{ui.RESET} {ui.GREY}{detail}{ui.RESET}")
        print()

        bad = [c for c in checks if not c[1]]
        if bad:
            ui.warn(f"{len(bad)} masalah. perbaiki yang gagal dulu.")
        else:
            ui.ok("semua sehat.")
