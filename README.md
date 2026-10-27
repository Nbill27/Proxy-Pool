# ppp — proxy pool terminal

Scraper proxy publik + penguji hidup/mati, dibungkus shell interaktif. Semua output
bahasa Indonesia, semua state disimpan sebagai file JSON/TXT di folder ini.

```
python cli.py            # mode interaktif (REPL)
python cli.py harvest    # sekali jalan
```

---

## 1. Pasang

```bash
pip install -r requirements.txt
```

Butuh Python 3.10+. Dependensi runtime cuma `aiohttp`; sisanya stdlib.

---

## 2. Mulai cepat

```bash
python cli.py
```

```
ppp> harvest
ppp> test --limit 300 --c 200
ppp> pool --limit 20
ppp> export env
```

Urutannya: **kumpulkan kandidat → uji hidup → simpan pool → export**.
`harvest` mengisi `candidates.txt`, `test` menulis `proxies.json`, `export` menyalin
pool ke format yang bisa langsung dipakai.

Kalau sumber mati atau kandidat kosong, jalankan `doctor` dulu — dia cek dependensi,
koneksi keluar, dan keberadaan file state.

---

## 3. Perintah

| perintah | arti |
|---|---|
| `status` | ringkasan kandidat, pool, jumlah sumber, status AI |
| `harvest [--timeout N]` | scrape semua sumber → `candidates.txt` |
| `import <ip:port ...>` | masukkan proxy manual (spasi/koma/newline bebas) |
| `import file <path>` | baca daftar dari file lokal |
| `import url <url>` | ambil daftar dari satu URL |
| `import paste` | tempel multiline, akhiri dengan baris berisi `.` |
| `test [--limit N] [--src cand\|pool] [--c N] [--timeout N]` | uji hidup → `proxies.json` |
| `pool [--sort lat\|ip] [--limit N]` | lihat isi pool (default sort `lat`, limit 40) |
| `export <json\|txt\|csv\|env> [path]` | simpan salinan pool |
| `check <ip:port> [--timeout N]` | uji satu proxy sekarang, tampilkan detail |
| `source list` | daftar URL sumber |
| `source add <url> [raw\|html]` | tambah sumber |
| `source rm <url>` | hapus sumber |
| `ai status` \| `ai ping` | kondisi lane AI / tes koneksi model |
| `ai farm [n] [--test]` | minta kandidat dari model (opsional langsung diuji) |
| `ai sources [n]` | minta URL sumber baru dari model |
| `ai review [n]` | minta model memilah pool yang sudah ada |
| `config` | tampilkan config (api_key disensor) |
| `config <key> <value>` | ubah config |
| `doctor` | diagnosa dependensi, koneksi, file |
| `clear` \| `help` \| `exit` | bersihkan layar / bantuan / keluar |

Ctrl+C membatalkan baris, Ctrl+D keluar. Panah atas/bawah = riwayat kalau `readline`
tersedia.

---

## 4. Catatan pemakaian

- `harvest` selalu menyimpan ke `candidates.txt`. Dedup otomatis, jadi harvest berulang aman.
- `test` default menguji kandidat (`--src cand`). Pakai `--src pool` untuk menguji ulang
  isi pool, berguna membuang yang sudah mati.
- `test` menggabungkan hasil, bukan menimpa: proxy yang sudah ada di pool dipertahankan
  kalau latensi barunya sama atau lebih baik.
- `export` tanpa path menulis ke `pool-<YYYYmmdd-HHMMSS>.<fmt>` di folder ini.
- `export env` menghasilkan `export HTTP_PROXY=...` plus komentar `# alt1..alt19`.
- `pool --sort lat` (default) urut dari tercepat; `--sort ip` urut leksikografis.
- Entri boleh ditulis bebas: `http://1.2.3.4:8080`, `1.2.3.4 8080`, atau `1.2.3.4:8080`
  semuanya diterima. Alamat privat dan reserved otomatis dibuang.
- Proxy transparan — yang meneruskan IP asli kamu — tidak disimpan.

---

## 5. Lane AI

AI di sini **OpenAI-compatible** — satu klien, banyak provider. Yang dibutuhkan cuma
`base_url`, `api_key`, `model`.

```bash
ppp> config ai.base_url https://api.openai.com/v1
ppp> config ai.api_key sk-...
ppp> config ai.model gpt-4o-mini
ppp> ai ping
```

Provider lain:

```bash
# Groq
config ai.base_url https://api.groq.com/openai/v1
config ai.model llama-3.3-70b-versatile

# OpenRouter
config ai.base_url https://openrouter.ai/api/v1
config ai.model anthropic/claude-3.5-sonnet

# Ollama (lokal, tanpa key)
config ai.base_url http://localhost:11434/v1
config ai.api_key ollama-local
config ai.model llama3.1

# LM Studio (lokal)
config ai.base_url http://localhost:1234/v1
config ai.api_key lmstudio
config ai.model local-model
```

Menyetel salah satu key `ai.*` otomatis menyalakan `ai.enabled`. Matikan dengan
`config ai.enabled false`. Kosongkan nilai dengan `-`:

```bash
config ai.api_key -        # hapus key
```

Yang paling berguna:

1. **`ai sources`** — usulan URL sumber baru untuk ditambahkan lewat `source add`.
2. **`ai review`** — memilah pool nyata: memberi label anonimitas dan mengurutkan mana
   yang layak dipakai.
3. **`ai farm --test`** — kandidat dari model, langsung diuji.

Kandidat dari model tidak dipercaya begitu saja: semuanya masuk antrean uji yang sama
dengan hasil scrape sebelum menyentuh `proxies.json`. Kalau AI gagal, dia melaporkan
gagal.

---

## 6. Arti hasil uji

Tiap proxy yang lolos punya lima kolom:

| kolom | arti |
|---|---|
| `proxy` | alamat `ip:port` |
| `exit_ip` | IP yang dilihat server tujuan |
| `scheme` | `https` kalau jalur TLS lewat proxy berhasil, `http` kalau cuma fallback |
| `latency_ms` | waktu total request lewat proxy |
| `anon` | `elite` kalau tidak ada header bocor; `anonymous` kalau ada `x-forwarded-for`, `x-real-ip`, `via`, atau `forwarded` |

Proxy dianggap hidup kalau request lewat proxy berhasil dan responsnya masuk akal.
Yang mati atau transparan tidak masuk pool.

---

## 7. Isi folder

| file | isi |
|---|---|
| `cli.py` | entry point; tanpa argumen = REPL, dengan argumen = sekali jalan |
| `ppp/engine.py` | scrape, parse, uji proxy |
| `ppp/store.py` | config, sumber, kandidat, pool, export |
| `ppp/ai.py` | klien AI + lane farm/sources/review |
| `ppp/shell.py` | REPL dan handler perintah |
| `ppp/ui.py` | warna, tabel, banner, progress bar |
| `config.json` | config aktif (dibuat otomatis) |
| `sources.json` | daftar URL sumber (dibuat otomatis) |
| `candidates.txt` | kandidat `ip:port`, satu per baris |
| `proxies.json` | pool hidup |
| `config.json.example` | contoh config untuk disalin |

`config.json` dan `sources.json` menyembuhkan diri: kalau hilang atau rusak, default
ditanam ulang saat pertama dibaca. Hapus `sources.json` kalau ingin balik ke daftar
sumber bawaan.

Warna mengikuti `NO_COLOR` — set variabel itu kalau pipe ke file atau log.

---

## 8. Kalau macet

**`harvest` dapat 0 kandidat** — jalankan `source list`, cek jumlahnya. Sumber publik
mati dan hidup bergiliran; matikan yang mati dengan `source rm <url>`.

**Semua hasil uji mati** — biasanya bukan proxy-nya, tapi jalur keluar kamu. Cek
`doctor`. `test` juga menampilkan IP asli kamu di pesan gagal; kalau itu `?`, masalahnya
di koneksi, bukan di proxy.

**`ai ping` gagal `ClientConnectorError`** — `base_url` menunjuk ke tempat yang tidak
ada. Untuk Ollama pastikan `ollama serve` jalan dan port-nya 11434.

**`ai ping` gagal 401** — api_key salah atau kosong. Untuk provider lokal, key apa pun
diterima asal tidak kosong.

**Terminal berantakan setelah Ctrl+C** — `clear`.

**Muncul `ConnectionResetError` / `WinError 10054` saat `test`** — proxy menutup koneksi
paksa. Tidak berbahaya, uji tetap berjalan.

**Uji terasa lambat** — proxy mati menunggu sampai timeout. Turunkan `--timeout` atau
`--c` kalau jaringan sedang goyang.
