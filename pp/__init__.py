"""Proxy Pool (PP) - proxy pool terminal.

Core package for the interactive CLI:
  engine  - scrape, parse, probe
  store   - config, sources, candidates, pool, export
  ai      - OpenAI-compatible assistant for farming
  ui      - colors, banner, tables, progress
  shell   - interactive REPL
"""

__version__ = "2.0.0"
__all__ = ["engine", "store", "ai", "ui", "shell"]
