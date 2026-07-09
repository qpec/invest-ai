"""tests/test_cluster.py — E.5 hidden-concentration clustering."""
import numpy as np
import pandas as pd
import pytest


def _returns(n=200, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 0.01, n)
    # A and B strongly correlated (>0.7); C independent
    a = base + rng.normal(0, 0.001, n)
    b = base + rng.normal(0, 0.001, n)
    c = rng.normal(0, 0.01, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"A": a, "B": b, "C": c}, index=idx)


def test_correlated_pair_clusters_together():
    from agentcy import cluster
    r = _returns()
    res = cluster.compute_clusters(r, {"A": 0.4, "B": 0.4, "C": 0.2}, threshold=0.7)
    assert res.memberships["A"] == res.memberships["B"]        # A,B together
    assert res.memberships["C"] != res.memberships["A"]        # C apart
    assert not res.stale and res.excluded == ()


def test_n_eff_matches_cluster_weights():
    from agentcy import cluster
    r = _returns()
    res = cluster.compute_clusters(r, {"A": 0.4, "B": 0.4, "C": 0.2}, threshold=0.7)
    # cluster {A,B}=0.8, {C}=0.2 -> N_eff = 1/(0.8^2 + 0.2^2) = 1/0.68 ≈ 1.47
    assert round(res.n_eff, 2) == 1.47


def test_short_history_excluded_and_own_cluster():
    from agentcy import cluster
    r = _returns()
    r.loc[r.index[:120], "C"] = np.nan          # C now has < 120 overlapping days
    res = cluster.compute_clusters(r, {"A": 0.4, "B": 0.4, "C": 0.2}, threshold=0.7)
    assert "C" in res.excluded and res.memberships["C"] not in {res.memberships["A"]}


def test_clustering_failure_is_stale():
    from agentcy import cluster
    empty = pd.DataFrame()
    res = cluster.compute_clusters(empty, {}, threshold=0.7)
    assert res.stale and res.memberships == {} and res.n_eff == 0.0


def test_single_symbol_is_own_cluster():
    from agentcy import cluster
    r = _returns()[["A"]]
    res = cluster.compute_clusters(r, {"A": 1.0}, threshold=0.7)
    assert res.n_eff == 1.0 and len(set(res.memberships.values())) == 1
