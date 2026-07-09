"""agentcy/cluster.py — E.5 local-currency correlation clustering, N_eff (pandas+scipy)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ClusterResult:
    memberships: Mapping[str, int]
    cluster_weights: Mapping[int, float]
    n_eff: float
    corr_matrix: pd.DataFrame
    excluded: tuple[str, ...] = ()
    stale: bool = False


def _n_eff(cluster_weights: Mapping[int, float]) -> float:
    denom = sum(w * w for w in cluster_weights.values())
    return 1.0 / denom if denom else 0.0


def _cluster_weights(memberships: Mapping[str, int], weights: Mapping[str, float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for sym, cid in memberships.items():
        out[cid] = out.get(cid, 0.0) + weights.get(sym, 0.0)
    return out


def compute_clusters(returns_local: pd.DataFrame, weights: Mapping[str, float], *,
                     threshold: float = 0.7) -> ClusterResult:
    """E.5: distance sqrt((1-corr)/2), average linkage, fcluster t=sqrt((1-threshold)/2);
    N_eff = 1/sum(w_c^2). <120 overlapping days -> own cluster + flag; failure -> stale."""
    empty = pd.DataFrame()
    try:
        if returns_local is None or returns_local.empty:
            return ClusterResult({}, {}, 0.0, empty, (), stale=True)
        # keep only columns with >= 120 non-NaN observations
        counts = returns_local.count()
        keep = [c for c in returns_local.columns if counts[c] >= 120]
        excluded = tuple(c for c in returns_local.columns if c not in keep)
        memberships: dict[str, int] = {}
        next_cid = 1
        corr = empty
        if len(keep) >= 2:
            sub = returns_local[keep].dropna()
            corr = sub.corr()
            from scipy.cluster.hierarchy import fcluster, linkage
            from scipy.spatial.distance import squareform
            dist = np.sqrt((1.0 - corr.to_numpy()) / 2.0)
            np.fill_diagonal(dist, 0.0)
            condensed = squareform(dist, checks=False)
            z = linkage(condensed, method="average")
            t = np.sqrt((1.0 - threshold) / 2.0)
            labels = fcluster(z, t=t, criterion="distance")
            memberships = {sym: int(lbl) for sym, lbl in zip(keep, labels)}
            next_cid = int(max(labels)) + 1
        else:
            for sym in keep:                               # 0 or 1 clusterable symbol -> singleton
                memberships[sym] = next_cid; next_cid += 1
        for sym in excluded:                               # each short-history symbol its own cluster
            memberships[sym] = next_cid; next_cid += 1
        cw = _cluster_weights(memberships, weights)
        return ClusterResult(memberships, cw, _n_eff(cw), corr, excluded, stale=False)
    except Exception:
        return ClusterResult({}, {}, 0.0, empty, (), stale=True)   # D.2: caller uses last week's
