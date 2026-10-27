"""Uji parser engine: regex, filter IP privat, input manual."""
from __future__ import annotations

import pytest

from ppp import engine


@pytest.mark.parametrize(
    "ip,port,ok",
    [
        ("8.8.8.8", "8080", True),
        ("1.1.1.1", "3128", True),
        ("10.0.0.1", "8080", False),
        ("127.0.0.1", "8080", False),
        ("172.16.0.1", "8080", False),
        ("172.31.255.255", "8080", False),
        ("172.32.0.1", "8080", True),
        ("192.168.1.1", "8080", False),
        ("0.0.0.0", "8080", False),
        ("224.0.0.1", "8080", False),
        ("255.255.255.255", "8080", False),
        ("8.8.8.8", "0", False),
        ("8.8.8.8", "65535", True),
        ("8.8.8.8", "65536", False),
        ("8.8.8", "8080", False),
        ("8.8.8.999", "8080", False),
        ("bukan.ip", "8080", False),
        ("100.64.0.1", "8080", False),
        ("100.127.255.255", "8080", False),
        ("100.128.0.1", "8080", True),
        ("169.254.1.1", "8080", False),
        ("198.18.0.1", "8080", False),
        ("198.19.255.255", "8080", False),
        ("198.20.0.1", "8080", True),
    ],
)
def test_valid(ip, port, ok):
    assert engine._valid(ip, port) is ok


@pytest.mark.parametrize(
    "raw,want",
    [
        ("http://1.2.3.4:8080", "1.2.3.4:8080"),
        ("socks5://1.2.3.4:1080", "1.2.3.4:1080"),
        ("  1.2.3.4 8080  ", "1.2.3.4:8080"),
        ("1.2.3.4:8080/", "1.2.3.4:8080"),
        ("1.2.3.4:8080\n", "1.2.3.4:8080"),
        ("http://10.0.0.1:8080", ""),
        ("http://0.0.0.0:80", ""),
        ("127.0.0.7:80", ""),
        ("", ""),
        ("bukan proxy", ""),
    ],
)
def test_normalize(raw, want):
    assert engine.normalize(raw) == want


def test_parse_raw_list():
    text = "8.8.8.8:8080\n1.1.1.1:3128\n"
    assert engine.parse(text) == {"8.8.8.8:8080", "1.1.1.1:3128"}


def test_parse_html_row():
    html = "<tr><td>8.8.8.8</td><td>8080</td></tr>"
    assert engine.parse(html) == {"8.8.8.8:8080"}


def test_parse_loose_separators():
    assert engine.parse("8.8.8.8 8080") == {"8.8.8.8:8080"}
    assert engine.parse("8.8.8.8,8080") == {"8.8.8.8:8080"}


def test_parse_drops_private():
    text = "10.0.0.1:8080\n192.168.1.1:3128\n8.8.8.8:8080"
    assert engine.parse(text) == {"8.8.8.8:8080"}


def test_parse_dedup():
    text = "8.8.8.8:8080\n8.8.8.8:8080\n"
    assert engine.parse(text) == {"8.8.8.8:8080"}


def test_parse_lines_comments_and_separators():
    text = "# komentar\n8.8.8.8:8080, 1.1.1.1:3128; 9.9.9.9:80\n"
    got = engine.parse_lines(text)
    assert "8.8.8.8:8080" in got
    assert "1.1.1.1:3128" in got
    assert "9.9.9.9:80" in got


def test_parse_lines_empty():
    assert engine.parse_lines("\n\n") == set()


def test_sample_respects_limit():
    items = [f"8.8.8.{i}:8080" for i in range(1, 51)]
    assert len(engine.sample(items, 0)) == 50
    assert len(engine.sample(items, 10)) == 10
    assert len(engine.sample(items, 999)) == 50


def test_summarize_empty():
    s = engine.summarize([])
    assert s["hidup"] == 0


def test_summarize_basic():
    rows = [
        {"proxy": "8.8.8.8:8080", "scheme": "https", "anon": "elite", "latency_ms": 100},
        {"proxy": "1.1.1.1:3128", "scheme": "http", "anon": "anonymous", "latency_ms": 300},
    ]
    s = engine.summarize(rows)
    assert s["hidup"] == 2
    assert s["https"] == 1
    assert s["elite"] == 1
    assert s["median_ms"] in (100, 300)
