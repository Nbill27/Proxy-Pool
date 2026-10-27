#!/usr/bin/env python3
"""ppp - proxy pool terminal.

Dua mode:
  interaktif   python cli.py             -> REPL interaktif
  satu tembak  python cli.py harvest
               python cli.py test --limit 200
               python cli.py ai farm 40 --test
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# readline: riwayat panah atas/bawah (opsional, tidak tersedia di semua platform)
try:
    import readline  # noqa: F401

    _HAS_READLINE = True
except Exception:
    _HAS_READLINE = False

from ppp import engine, shell, ui


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="ppp",
        description="proxy pool terminal - scrape, probe, pool",
        epilog="tanpa argumen = mode interaktif",
    )
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("shell", help="mulai mode interaktif (default)")
    sub.add_parser("help", help="daftar perintah")
    sub.add_parser("status", help="ringkasan state")
    sub.add_parser("doctor", help="cek dependensi dan koneksi")

    h = sub.add_parser("harvest", help="scrape semua sumber")
    h.add_argument("--timeout", type=int)

    t = sub.add_parser("test", help="uji kandidat/pool")
    t.add_argument("--limit", type=int, default=0)
    t.add_argument("--src", choices=["cand", "pool"], default="cand")
    t.add_argument("-c", "--concurrency", type=int)
    t.add_argument("--timeout", type=int)

    p = sub.add_parser("pool", help="lihat pool")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--sort", choices=["lat", "ip"], default="lat")

    e = sub.add_parser("export", help="export pool")
    e.add_argument("format", nargs="?", default="txt", choices=["json", "txt", "csv", "env"])
    e.add_argument("path", nargs="?")

    c = sub.add_parser("check", help="uji satu proxy")
    c.add_argument("proxy")

    i = sub.add_parser("import", help="import proxy manual")
    i.add_argument("items", nargs="+", help="ip:port ... | file <path> | url <url>")

    s = sub.add_parser("source", help="kelola sumber")
    s.add_argument("action", nargs="?", default="list", choices=["list", "add", "rm"])
    s.add_argument("value", nargs="?")
    s.add_argument("kind", nargs="?", default="raw")

    a = sub.add_parser("ai", help="lane AI")
    a.add_argument("action", nargs="?", default="status", choices=["status", "ping", "farm", "sources", "review"])
    a.add_argument("n", nargs="?", type=int)
    a.add_argument("--test", action="store_true")

    cfg = sub.add_parser("config", help="lihat/ubah config")
    cfg.add_argument("key", nargs="?")
    cfg.add_argument("value", nargs="*")

    return ap


def to_shell_args(ns: argparse.Namespace) -> list[str]:
    """Ubah namespace argparse jadi argv gaya shell internal."""
    cmd = ns.cmd
    if cmd == "harvest":
        return ["harvest"] + (["--timeout", str(ns.timeout)] if ns.timeout else [])
    if cmd == "test":
        args = ["test", "--src", ns.src]
        if ns.limit:
            args += ["--limit", str(ns.limit)]
        if ns.concurrency:
            args += ["--c", str(ns.concurrency)]
        if ns.timeout:
            args += ["--timeout", str(ns.timeout)]
        return args
    if cmd == "pool":
        return ["pool", "--limit", str(ns.limit), "--sort", ns.sort]
    if cmd == "export":
        return ["export", ns.format] + ([ns.path] if ns.path else [])
    if cmd == "check":
        return ["check", ns.proxy]
    if cmd == "import":
        return ["import"] + ns.items
    if cmd == "source":
        return ["source", ns.action] + ([ns.value] if ns.value else []) + (
            [ns.kind] if ns.action == "add" and ns.kind else []
        )
    if cmd == "ai":
        args = ["ai", ns.action] + ([str(ns.n)] if ns.n else [])
        if ns.test:
            args.append("--test")
        return args
    if cmd == "config":
        return ["config"] + ([ns.key] if ns.key else []) + list(ns.value or [])
    return [cmd] if cmd else []


async def main_async(argv: list[str]) -> int:
    ap = build_parser()
    ns = ap.parse_args(argv)

    engine.quiet_loop(asyncio.get_running_loop())
    sh = shell.Shell()

    if not ns.cmd or ns.cmd == "shell":
        await sh.run()
        return 0

    args = to_shell_args(ns)
    await sh.dispatch(" ".join(args))
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async(sys.argv[1:]))
    except KeyboardInterrupt:
        print()
        return 130
    except ModuleNotFoundError as e:
        if "aiohttp" in str(e):
            ui.err("aiohttp belum terpasang")
            ui.note("pip install aiohttp")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
