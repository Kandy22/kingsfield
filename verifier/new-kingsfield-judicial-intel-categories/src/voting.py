"""F25 Jury and Voting Models — panel probability math. Pure functions.

Condorcet jury theorem: if each of n voters is independently correct with
probability p and the group decides by majority, the probability the majority
is correct is the upper tail of Binomial(n, p). For a 3-judge appellate panel
with p = 0.7 that is 0.784; with p = 0.5 it is 0.5.

Banzhaf power index: for weighted voting with a quota, a voter's power is the
share of winning coalitions in which they are critical. On an equal-weight
3-judge majority panel every judge is 1/3 — the function exists for the
general case (en banc courts, juries with supermajority rules).

These state assumptions (independence, a fixed p) that real panels violate;
the result is a model output, labelled as such, never a fact about a court.
"""
from __future__ import annotations

from itertools import combinations
from math import comb

from value_types import VotingModelResult


def condorcet_majority(n: int, p: float) -> float:
    """P(majority of n independent voters is correct | each correct w.p. p)."""
    if n < 1 or not (0.0 <= p <= 1.0):
        raise ValueError("n >= 1 and 0 <= p <= 1")
    k_min = n // 2 + 1
    return sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(k_min, n + 1))


def banzhaf(weights: list[int], quota: int) -> list[float]:
    """Normalized Banzhaf index per voter for a weighted majority game."""
    n = len(weights)
    if n == 0 or quota <= 0:
        raise ValueError("need voters and a positive quota")
    swings = [0] * n
    idx = range(n)
    for r in range(1, n + 1):
        for coalition in combinations(idx, r):
            total = sum(weights[i] for i in coalition)
            if total < quota:
                continue
            for i in coalition:
                if total - weights[i] < quota:
                    swings[i] += 1
    s = sum(swings)
    return [x / s if s else 0.0 for x in swings]


def condorcet_result(n: int, p: float) -> VotingModelResult:
    return {
        "model": "condorcet_majority",
        "params": {"n": n, "p": p, "assumes": "independent voters, identical competence"},
        "result": {"p_majority_correct": round(condorcet_majority(n, p), 4)},
        "note": "Model output under stated assumptions; not a measured property of any court.",
    }


def banzhaf_result(weights: list[int], quota: int) -> VotingModelResult:
    return {
        "model": "banzhaf",
        "params": {"weights": weights, "quota": quota},
        "result": {"index": [round(x, 4) for x in banzhaf(weights, quota)]},
        "note": "Normalized Banzhaf power index for the stated weighted-majority game.",
    }


if __name__ == "__main__":
    for p in (0.5, 0.6, 0.7, 0.8):
        print(f"3-judge panel, p={p}: P(majority correct) = {condorcet_majority(3, p):.3f}")
    print("3-judge equal panel Banzhaf:", banzhaf([1, 1, 1], 2))
    print("7-member en banc, 4 to win:", banzhaf([1] * 7, 4))
    print("12-person jury, unanimity:", banzhaf([1] * 12, 12))
