"""Tampilan terminal: warna ANSI, banner, tabel, progress. Semua stdlib."""
from __future__ import annotations

import os
import shutil
import sys
import time

# konsol windows default cp1252 -- paksa utf-8 supaya karakter box tidak pecah
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- warna
_ENABLE = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str) -> str:
    return f"\033[{code}m" if _ENABLE else ""


RESET = _c("0")
BOLD = _c("1")

RED = _c("38;5;203")
GREEN = _c("38;5;114")
YELLOW = _c("38;5;221")
BLUE = _c("38;5;75")
CYAN = _c("38;5;80")
GREY = _c("38;5;244")
GREY2 = _c("38;5;239")

# glyph P (ANSI shadow) -- dibangun dari satu sumber supaya tidak ada huruf yang kepotong
_P_GLYPH = [
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2557 ",
    "\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557",
    "\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d",
    "\u2588\u2588\u2554\u2550\u2550\u2550\u255d ",
    "\u2588\u2588\u2551     ",
    "\u255a\u2550\u255d     ",
]

BANNER = "\n".join(
    "".join(row.ljust(9) for _ in range(2)) + row.rstrip()
    for row in _P_GLYPH
)

ART_COLORS = ["1;36", "36", "1;34", "34", "1;32", "32"]

TAGLINE = [
    ("P R O X Y   P O O L", "1;37"),
    ("scrape  ->  probe  ->  pool", "38"),
]


def width(default: int = 78) -> int:
    try:
        w = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        w = default
    return max(40, min(w, 120))


def _cls() -> None:
    """Bersihkan layar saja, tanpa menggambar apa pun."""
    if _ENABLE:
        sys.stdout.write("\033[2J\033[H")
    else:
        sys.stdout.write("\n" * 40)
    sys.stdout.flush()


def out(text: str = "") -> None:
    print(text)


def hr(ch: str = "-") -> None:
    print(GREY2 + ch * width() + RESET)


def banner(sub: str = "") -> None:
    art = BANNER.strip("\n").split("\n")
    for i, line in enumerate(art):
        color = ART_COLORS[min(i, len(ART_COLORS) - 1)]
        print(f"    {_c(color)}{line}{RESET}")
    print()
    for text, color in TAGLINE:
        print(f"    {_c(color)}{text}{RESET}")
    print()
    if sub:
        print(f"    {GREY}{sub}{RESET}")
        print()


# ---------------------------------------------------------------- pesan
def clear() -> None:
    """Bersihkan layar, lalu gambar ulang banner."""
    _cls()
    banner()


def ok(msg: str) -> None:
    print(f"  {GREEN}ok{RESET}   {msg}")


def info(msg: str) -> None:
    print(f"  {BLUE}info{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}warn{RESET} {msg}")


def err(msg: str) -> None:
    print(f"  {RED}gagal{RESET} {msg}")


def note(msg: str) -> None:
    print(f"  {GREY}{msg}{RESET}")


def item(k: str, v: str, kw: int = 16) -> None:
    print(f"  {GREY}{k:<{kw}}{RESET}{v}")


def label(text: str) -> None:
    print(f"{BOLD}{CYAN}{text}{RESET}")


# ---------------------------------------------------------------- tabel
def _fit(cells: list[str], widths: list[int]) -> list[str]:
    out_cells = []
    for cell, w in zip(cells, widths, strict=False):
        s = str(cell)
        if len(s) > w:
            s = s[: max(1, w - 1)] + "~"
        out_cells.append(s.ljust(w))
    return out_cells


def table(headers: list[str], rows: list[list[str]], colorize=None, max_rows: int = 0) -> None:
    """Tabel teks polos dengan garis tipis. Tidak butuh rich."""
    if not rows:
        note("(kosong)")
        return
    cols = len(headers)
    all_rows = [[str(c) for c in r] + [""] * (cols - len(r)) for r in rows]
    widths = []
    for i in range(cols):
        w = max([len(headers[i])] + [len(r[i]) for r in all_rows])
        widths.append(min(w, 46))

    total = sum(widths) + 2 * (cols - 1)
    limit = width()
    if total > limit:
        widths[-1] = max(6, widths[-1] - (total - limit))

    head = _fit(headers, widths)
    print(f"{GREY2}+{'+'.join('-' * (w + 2) for w in widths)}+{RESET}")
    print(f"{GREY2}|{RESET} " + f" {GREY2}|{RESET} ".join(f"{BOLD}{h}{RESET}" for h in head) + f" {GREY2}|{RESET}")
    print(f"{GREY2}+{'+'.join('-' * (w + 2) for w in widths)}+{RESET}")

    shown = all_rows[:max_rows] if max_rows else all_rows
    for r in shown:
        cells = _fit(r, widths)
        painted = [colorize(i, c) if colorize else c for i, c in enumerate(cells)]
        print(f"{GREY2}|{RESET} " + f" {GREY2}|{RESET} ".join(painted) + f" {GREY2}|{RESET}")
    print(f"{GREY2}+{'+'.join('-' * (w + 2) for w in widths)}+{RESET}")
    if max_rows and len(all_rows) > max_rows:
        note(f"... {len(all_rows) - max_rows} baris lagi disembunyikan")


def _strip(s: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", s)


# ---------------------------------------------------------------- progress
class Bar:
    """Progress bar satu baris, ditimpa tiap update."""

    def __init__(self, total: int, prefix: str = ""):
        self.total = max(1, total)
        self.prefix = prefix
        self.start = time.perf_counter()
        self.last = 0.0
        self.width = min(34, max(14, width() - 46))

    def update(self, done: int, extra: str = "", force: bool = False) -> None:
        now = time.perf_counter()
        if not force and now - self.last < 0.08:
            return
        self.last = now
        extra = str(extra)[:24]
        frac = min(1.0, done / self.total)
        filled = int(self.width * frac)
        bar = f"{GREEN}{'#' * filled}{GREY2}{'.' * (self.width - filled)}{RESET}"
        pct = int(frac * 100)
        elapsed = now - self.start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (self.total - done) / rate if rate > 0 else 0
        line = (
            f"\r  {self.prefix} [{bar}] {done:>5}/{self.total} {pct:>3}% "
            f"{GREY}{rate:>6.1f}/s eta {eta:>4.0f}s {extra}{RESET}"
        )
        sys.stdout.write(line)
        sys.stdout.flush()
        if done >= self.total:
            sys.stdout.write("\n")
            sys.stdout.flush()


def rule(text: str = "") -> None:
    if not text:
        hr()
        return
    w = width()
    left = f"{GREY2}{'-' * 2}{RESET} {BOLD}{text}{RESET} "
    pad = max(0, w - len(_strip(left)) - 2)
    print(left + f"{GREY2}{'-' * pad}{RESET}")


def kv_table(data: dict, key_w: int = 18) -> None:
    for k, v in data.items():
        item(str(k), str(v), key_w)
