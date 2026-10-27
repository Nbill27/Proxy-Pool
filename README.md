# Proxy Pool (PP)

Public proxy scraper + liveness tester, wrapped in an interactive shell. Every state
file lives in this folder as JSON/TXT.

```
python cli.py            # interactive mode (REPL)
python cli.py harvest    # one-shot
```

---

## 1. Install

```bash
pip install -r requirements.txt
```

Python 3.10+. The only runtime dependency is `aiohttp`; everything else is stdlib.

Optional, to get the `pp` command on your PATH:

```bash
pip install -e .
```

---

## 2. Quick start

```bash
python cli.py
```

```
pp> harvest
pp> test --limit 300 --c 200
pp> pool --limit 20
pp> export env
```

The order is always: **collect candidates → test liveness → save pool → export**.
`harvest` fills `candidates.txt`, `test` writes `proxies.json`, `export` copies the
pool into a format you can use right away.

If sources are down or candidates are empty, run `doctor` first — it checks
dependencies, the outbound connection, and the state files.

---

## 3. Commands

| command | meaning |
|---|---|
| `status` | summary of candidates, pool, source count, AI status |
| `harvest [--timeout N]` | scrape every source → `candidates.txt` |
| `import <ip:port ...>` | add proxies manually (spaces/commas/newlines allowed) |
| `import file <path>` | read a list from a local file |
| `import url <url>` | fetch a list from a single URL |
| `import paste` | paste multiline, finish with a line containing `.` |
| `test [--limit N] [--src cand\|pool] [--c N] [--timeout N]` | test liveness → `proxies.json` |
| `pool [--sort lat\|ip] [--limit N]` | show the pool (default sort `lat`, limit 40) |
| `export <json\|txt\|csv\|env> [path]` | save a copy of the pool |
| `check <ip:port> [--timeout N]` | test one proxy now, show details |
| `source list` | list source URLs |
| `source add <url> [raw\|html]` | add a source |
| `source rm <url>` | remove a source |
| `ai status` \| `ai ping` | AI lane status / test the model connection |
| `ai farm [n] [--test]` | ask the model for candidates (optionally test them) |
| `ai sources [n]` | ask the model for new source URLs |
| `ai review [n]` | ask the model to rank the existing pool |
| `config` | show config (api_key masked) |
| `config <key> <value>` | change config |
| `doctor` | diagnose dependencies, connection, files |
| `clear` \| `help` \| `exit` | clear screen / help / quit |

Ctrl+C cancels the current line, Ctrl+D quits. Up/down arrows walk the history when
`readline` is available.

---

## 4. Usage notes

- `harvest` always saves to `candidates.txt`. Dedup happens on write, so repeated
  harvests are safe.
- `test` reads candidates by default (`--src cand`). Use `--src pool` to re-test the
  pool, which is handy for dropping dead entries.
- `test` merges results instead of overwriting: an existing pool entry is kept unless
  the new latency is better.
- `export` without a path writes `pool-<YYYYmmdd-HHMMSS>.<fmt>` in this folder.
- `export env` emits `export HTTP_PROXY=...` plus `# alt1..alt19` comments.
- `pool --sort lat` (default) goes fastest first; `--sort ip` sorts lexicographically.
- Entries can be written loosely: `http://1.2.3.4:8080`, `1.2.3.4 8080`, and
  `1.2.3.4:8080` are all accepted. Private and reserved addresses are dropped.
- Transparent proxies — the ones that leak your real IP — are never stored.

---

## 5. AI lane

The AI here is **OpenAI-compatible** — one client, many providers. All it needs is
`base_url`, `api_key`, and `model`.

```bash
pp> config ai.base_url https://api.openai.com/v1
pp> config ai.api_key sk-...
pp> config ai.model gpt-4o-mini
pp> ai ping
```

Other providers:

```bash
# Groq
config ai.base_url https://api.groq.com/openai/v1
config ai.model llama-3.3-70b-versatile

# OpenRouter
config ai.base_url https://openrouter.ai/api/v1
config ai.model anthropic/claude-3.5-sonnet

# Ollama (local, no key)
config ai.base_url http://localhost:11434/v1
config ai.api_key ollama-local
config ai.model llama3.1

# LM Studio (local)
config ai.base_url http://localhost:1234/v1
config ai.api_key lmstudio
config ai.model local-model
```

Setting any `ai.*` key turns `ai.enabled` on automatically. Turn it off with
`config ai.enabled false`. Clear a value with `-`:

```bash
config ai.api_key -        # remove the key
```

What is actually useful:

1. **`ai sources`** — proposed source URLs to add with `source add`.
2. **`ai review`** — ranks the real pool and labels anonymity.
3. **`ai farm --test`** — candidates from the model, tested immediately.

Candidates from the model are not trusted as-is: they go through the same test queue
as scraped ones before touching `proxies.json`. If the AI fails, it reports a failure.

---

## 6. Test result fields

Every proxy that survives has five fields:

| field | meaning |
|---|---|
| `proxy` | the `ip:port` address |
| `exit_ip` | the IP the target server sees |
| `scheme` | `https` if TLS through the proxy worked, `http` if only the fallback did |
| `latency_ms` | total request time through the proxy |
| `anon` | `elite` when no header leaks; `anonymous` when `x-forwarded-for`, `x-real-ip`, `via`, or `forwarded` shows up |

A proxy counts as alive when a request through it succeeds and the response looks
sane. Dead or transparent proxies never enter the pool.

---

## 7. Folder contents

| file | contents |
|---|---|
| `cli.py` | entry point; no arguments = REPL, with arguments = one-shot |
| `pp/engine.py` | scrape, parse, test proxies |
| `pp/store.py` | config, sources, candidates, pool, export |
| `pp/ai.py` | AI client + farm/sources/review lanes |
| `pp/shell.py` | REPL and command handlers |
| `pp/ui.py` | colors, tables, banner, progress bar |
| `config.json` | active config (created automatically) |
| `sources.json` | source URL list (created automatically) |
| `candidates.txt` | `ip:port` candidates, one per line |
| `proxies.json` | live pool |
| `config.json.example` | sample config to copy |

`config.json` and `sources.json` are self-healing: if they go missing or get corrupted,
the defaults are written back on first read. Delete `sources.json` to return to the
built-in source list.

Data lives in this folder when running from source, or in `~/.pp` when installed as a
package. Override it with `PP_HOME`.

Colors follow `NO_COLOR` — set that variable when piping to a file or a log.

---

## 8. Troubleshooting

**`harvest` returns 0 candidates** — run `source list` and check the count. Public
sources come and go; remove the dead ones with `source rm <url>`.

**Every test comes back dead** — it is usually your outbound path, not the proxies.
Run `doctor`. `test` also prints your real IP in the failure message; if that is `?`,
the problem is the connection, not the proxy.

**`ai ping` fails with `ClientConnectorError`** — `base_url` points somewhere that does
not exist. For Ollama, make sure `ollama serve` is running on port 11434.

**`ai ping` fails with 401** — wrong or empty api_key. Local providers accept any
non-empty key.

**The terminal looks messy after Ctrl+C** — `clear`.

**`ConnectionResetError` / `WinError 10054` shows up during `test`** — a proxy closed
the connection abruptly. Harmless; the test keeps running.

**Testing feels slow** — dead proxies wait for the timeout. Lower `--timeout` or `--c`
when the network is shaky.
