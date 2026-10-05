from __future__ import annotations

import math
import random


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * tp / (2 * tp + fp + fn) if tp else 0.0)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def cluster_bootstrap(clusters: list[tuple], statistic, n: int = 2000, seed: int = 0,
                      level: float = 0.95) -> tuple[float, float]:
    """Percentile interval for `statistic(*summed counts)`, resampling whole clusters with replacement.

    Rows that share a cluster are correlated, so they are resampled together; a statistic that is
    undefined for a resample (returns None) drops that resample.
    """
    rng = random.Random(seed)
    values = []
    for _ in range(n if clusters else 0):
        total = [0] * len(clusters[0])
        for _ in clusters:
            for i, count in enumerate(clusters[rng.randrange(len(clusters))]):
                total[i] += count
        value = statistic(*total)
        if value is not None:
            values.append(value)
    if not values:
        return 0.0, 1.0
    tail = (1 - level) / 2
    return percentile(values, tail), percentile(values, 1 - tail)


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def cohen_kappa(a: list[bool], b: list[bool]) -> float:
    if len(a) != len(b):
        raise ValueError("label sets differ in length")
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    if chance == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - chance) / (1 - chance)
