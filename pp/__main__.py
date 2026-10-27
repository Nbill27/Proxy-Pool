"""Package entry point: run `python -m pp`."""
from __future__ import annotations

import asyncio
import sys


def _main() -> int:
    try:
        from cli import main
    except ImportError:
        from . import shell

        try:
            asyncio.run(shell.Shell().run())
        except KeyboardInterrupt:
            print()
            return 130
        return 0
    return main()


if __name__ == "__main__":
    sys.exit(_main())
