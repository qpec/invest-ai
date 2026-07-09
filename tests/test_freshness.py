"""Stamped values and check states (contracts §3.3)."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from agentcy.freshness import CheckResult, DataState, Stamped


def test_data_state_values():
    assert DataState.FRESH == "fresh"
    assert DataState.STALE == "stale"
    assert DataState.BOOTSTRAPPING == "bootstrapping"


def test_check_result_five_states():
    assert {r.value for r in CheckResult} == {
        "PASS", "FIRE", "STALE", "BOOTSTRAPPING", "UNVERIFIABLE"}


def test_stamped_usable_only_when_fresh():
    at = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)
    assert Stamped(1.23, at).usable()
    assert not Stamped(1.23, at, state=DataState.STALE, note="14d old").usable()
    assert not Stamped(1.23, at, state=DataState.BOOTSTRAPPING).usable()


def test_stamped_is_frozen_and_carries_provenance():
    at = datetime(2026, 7, 8, 5, 0, tzinfo=timezone.utc)
    s = Stamped("x", at)
    assert s.fetched_at == at and s.note is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.value = "y"
