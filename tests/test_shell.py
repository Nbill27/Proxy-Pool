"""Uji helper parsing argumen di shell: flag bernilai vs flag saklar."""
from __future__ import annotations

from ppp import shell


def test_switch_detects_trailing_flag():
    assert shell._switch(["farm", "40", "--test"], "--test") is True


def test_switch_absent():
    assert shell._switch(["farm", "40"], "--test") is False


def test_flag_reads_value():
    assert shell._flag(["test", "--limit", "10"], "--limit") == "10"


def test_flag_missing_value_returns_default():
    assert shell._flag(["farm", "--test"], "--test") is None
