#!/usr/bin/env python3
"""Proxy Pool (PP) - proxy pool terminal.

Two modes:
  interactive  python cli.py             -> interactive REPL
  one-shot     python cli.py harvest
               python cli.py test --limit 200
               python cli.py ai farm 40 --test
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# readline: up/down arrow history (optional, not available on every platform)
try:
    import readline  # noqa: F401

    _HAS_READLINE = True
except Exception:
    _HAS_READLINE = False

from pp import engine, shell, ui


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="pp",
        description="Proxy Pool terminal - scrape, probe, pool",
        epilog="no arguments = interactive mode",
    )
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("shell", help="start interactive mode (default)")
    sub.add_parser("help", help="command list")
    sub.add_parser("status", help="state summary")
    sub.add_parser("doctor", help="check dependencies and connection")

    h = sub.add_parser("harvest", help="scrape all sources")
    h.add_argument("--timeout", type=int)

    t = sub.add_parser("test", help="test candidates/pool")
    t.add_argument("--limit", type=int, default=0)
    t.add_argument("--src", choices=["cand", "pool"], default="cand")
    t.add_argument("-c", "--concurrency", type=int)
    t.add_argument("--timeout", type=int)

    p = sub.add_parser("pool", help="show pool")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--sort", choices=["lat", "ip"], default="lat")

    e = sub.add_parser("export", help="export pool")
    e.add_argument("format", nargs="?", default="txt", choices=["json", "txt", "csv", "env"])
    e.add_argument("path", nargs="?")

    c = sub.add_parser("check", help="test one proxy")
    c.add_argument("proxy")

    i = sub.add_parser("import", help="import proxies manually")
    i.add_argument("items", nargs="+", help="ip:port ... | file <path> | url <url>")

    s = sub.add_parser("source", help="manage sources")
    s.add_argument("action", nargs="?", default="list", choices=["list", "add", "rm"])
    s.add_argument("value", nargs="?")
    s.add_argument("kind", nargs="?", default="raw")

    a = sub.add_parser("ai", help="AI lane")
    a.add_argument("action", nargs="?", default="status", choices=["status", "ping", "farm", "sources", "review"])
    a.add_argument("n", nargs="?", type=int)
    a.add_argument("--test", action="store_true")

    cfg = sub.add_parser("config", help="view/change config")
    cfg.add_argument("key", nargs="?")
    cfg.add_argument("value", nargs="*")

    return ap


def to_shell_args(ns: argparse.Namespace) -> list[str]:
    """Turn an argparse namespace into internal shell-style argv."""
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
            ui.err("aiohttp is not installed")
            ui.note("pip install aiohttp")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
