"""Uji penyimpanan: urutan kandidat, merge pool, dan semua format export."""
from __future__ import annotations

import json

import pytest

from ppp import store


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Alihkan semua file data ke direktori sementara."""
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "CANDIDATES_FILE", tmp_path / "candidates.txt")
    monkeypatch.setattr(store, "POOL_FILE", tmp_path / "proxies.json")
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(store, "SOURCES_FILE", tmp_path / "sources.json")
    return tmp_path


def test_add_candidates_counts(sandbox):
    total, new = store.add_candidates(["8.8.8.8:8080", "1.1.1.1:3128"])
    assert (total, new) == (2, 2)

    total, new = store.add_candidates(["8.8.8.8:8080", "9.9.9.9:80"])
    assert (total, new) == (3, 1)


def test_add_candidates_keeps_insertion_order(sandbox):
    store.add_candidates(["9.9.9.9:80", "8.8.8.8:8080", "1.1.1.1:3128"])
    store.add_candidates(["5.5.5.5:3128"])

    assert store.load_candidates() == [
        "9.9.9.9:80",
        "8.8.8.8:8080",
        "1.1.1.1:3128",
        "5.5.5.5:3128",
    ]


def test_add_candidates_ignores_blank(sandbox):
    total, new = store.add_candidates(["", "  ", "8.8.8.8:8080"])
    assert (total, new) == (1, 1)


def test_add_candidates_normalizes_scheme_and_dedups(sandbox):
    total, new = store.add_candidates(["http://8.8.8.8:8080", "8.8.8.8:8080"])
    assert (total, new) == (1, 1)
    assert store.load_candidates() == ["8.8.8.8:8080"]


def test_load_candidates_heals_polluted_file(sandbox):
    store.CANDIDATES_FILE.write_text(
        "http://8.8.8.8:8080\nhttp://0.0.0.0:80\n127.0.0.7:80\n1.1.1.1 3128\n",
        encoding="utf-8",
    )
    assert store.load_candidates() == ["8.8.8.8:8080", "1.1.1.1:3128"]


def test_merge_pool_keeps_better_latency(sandbox):
    store.merge_pool([{"proxy": "8.8.8.8:8080", "latency_ms": 500, "scheme": "http", "anon": "elite"}])
    total, added = store.merge_pool(
        [{"proxy": "8.8.8.8:8080", "latency_ms": 120, "scheme": "http", "anon": "elite"}]
    )
    assert (total, added) == (1, 0)

    rows = store.load_pool()
    assert rows[0]["latency_ms"] == 120


def test_merge_pool_skips_bad_latency(sandbox):
    store.merge_pool([{"proxy": "8.8.8.8:8080", "latency_ms": 100, "scheme": "http", "anon": "elite"}])
    store.merge_pool([{"proxy": "8.8.8.8:8080", "latency_ms": 900, "scheme": "http", "anon": "elite"}])
    assert store.load_pool()[0]["latency_ms"] == 100


def test_merge_pool_ignores_entries_without_proxy(sandbox):
    total, added = store.merge_pool([{"latency_ms": 10}])
    assert (total, added) == (0, 0)


ROWS = [
    {"proxy": "8.8.8.8:8080", "exit_ip": "8.8.8.8", "scheme": "https", "latency_ms": 120, "anon": "elite"},
    {"proxy": "1.1.1.1:3128", "exit_ip": "1.1.1.1", "scheme": "http", "latency_ms": 300, "anon": "anonymous"},
]


def test_export_json(sandbox):
    path = store.export_pool("json", ROWS, sandbox / "out.json")
    assert json.loads(path.read_text(encoding="utf-8")) == ROWS


def test_export_txt(sandbox):
    path = store.export_pool("txt", ROWS, sandbox / "out.txt")
    assert path.read_text(encoding="utf-8").splitlines() == ["8.8.8.8:8080", "1.1.1.1:3128"]


def test_export_csv(sandbox):
    path = store.export_pool("csv", ROWS, sandbox / "out.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "proxy,exit_ip,scheme,latency_ms,anon"
    assert "8.8.8.8:8080" in lines[1]


def test_export_env(sandbox):
    path = store.export_pool("env", ROWS, sandbox / "out.env")
    text = path.read_text(encoding="utf-8")
    assert "export HTTP_PROXY=http://8.8.8.8:8080" in text
    assert "# alt2: http://1.1.1.1:3128" in text


def test_export_env_empty(sandbox):
    path = store.export_pool("env", [], sandbox / "out.env")
    assert path.read_text(encoding="utf-8").strip() == "# kosong"


def test_export_unknown_format(sandbox):
    with pytest.raises(ValueError):
        store.export_pool("xml", ROWS, sandbox / "out.xml")


def test_config_roundtrip(sandbox):
    cfg = store.load_config()
    cfg["timeout"] = 21
    cfg["ai"]["enabled"] = True
    store.save_config(cfg)

    again = store.load_config()
    assert again["timeout"] == 21
    assert again["ai"]["enabled"] is True
    assert again["ai"]["model"] == cfg["ai"]["model"]


def test_sources_self_heal(sandbox):
    assert store.load_sources() == store.DEFAULT_SOURCES
    assert store.SOURCES_FILE.exists()
