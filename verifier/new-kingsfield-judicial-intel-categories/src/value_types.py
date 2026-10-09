"""Schemas for the `value_type` strings named in data/catalog.json.

The catalog names a value type per fact ("named_share[]", "appeals_row", …) but
does not define it. These TypedDicts are the definitions; types.ts mirrors them.
Only types a producer can populate today are fully specified; the rest are
declared so a snapshot can carry them once a source exists.

Every populated value also carries, at the snapshot level, a provenance entry
{source, collected_at}. Counts and rates here are arithmetic on public records;
nothing in this module calls a model.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


# ---- primitives ------------------------------------------------------------

class NamedShare(TypedDict):
    name: str
    count: int
    share: float            # 0..1 of the total the distribution was computed over


class DurationDays(TypedDict):
    n: int
    median: float
    mean: float
    p10: float
    p90: float
    from_event: str         # e.g. "oral_argument"
    to_event: str           # e.g. "decision"


class CI95(TypedDict):
    lo: float
    hi: float
    method: Literal["wilson"]


# ---- M4 / M6 ---------------------------------------------------------------

class AppealsYearRow(TypedDict):
    year: int
    n: int
    reversal_rate: float


class AppealsRow(TypedDict):
    """F19. Reversal here means the appellate court reversed in whole or in part."""
    scope: Literal["court", "appellate_judge_panels", "trial_judge_trail"]
    n: int
    affirmed: int
    reversed: int           # whole reversals (incl. vacated / quashed)
    mixed: int              # affirmed in part / reversed in part
    other: int              # dismissed / denied / granted / unknown
    reversal_rate: float    # (reversed + mixed) / (affirmed + reversed + mixed)
    reversal_rate_ci95: CI95
    pca_share: NotRequired[float]       # court scope: share of all dispositions that are one-line PCAs
    argued_share: NotRequired[float]    # court scope: share of dispositions that had oral argument on video
    by_year: NotRequired[list[AppealsYearRow]]


class MilestoneForecast(TypedDict):
    """F17. Quantiles of an empirical distribution, not a model output."""
    milestone: str          # e.g. "decision"
    from_event: str         # e.g. "oral_argument"
    n: int
    p50_days: float
    p80_days: float
    p90_days: float
    basis: str


class ProbabilityCard(TypedDict):
    """F26. The catalog's rule: calibrate or abstain. `abstain` is True when the
    calibration bin is too small or too close to the base rate to say anything."""
    outcome: str            # "affirm"
    p: float | None
    base_rate: float
    n_calibration: int
    bin: str                # the calibration bin the case fell into
    abstain: bool
    why: str
    inputs: dict[str, Any]  # the signals the bin was chosen on (all Jev outputs are named here)


class DecisionLeaf(TypedDict):
    leaf: bool
    n: int
    p_affirm: float
    label: str


class DecisionNode(TypedDict):
    leaf: bool
    feature: str
    op: Literal[">=", "<=", "=="]
    threshold: float | str
    left: "DecisionNode | DecisionLeaf"     # condition true
    right: "DecisionNode | DecisionLeaf"    # condition false


class DecisionTree(TypedDict):
    """F22. An if-then approximation fit to observed splits. Every leaf carries
    its support so a reader can see what the rule is standing on."""
    target: str
    fit_on: str
    n: int
    root: DecisionNode | DecisionLeaf
    rules_text: list[str]


class CounselJudgeRow(TypedDict):
    """F29 / F21. `wins` is outcome-for-the-side (appellant: reversed or mixed;
    appellee: affirmed). Rows with n below the floor are suppressed by the
    producer, per the catalog note — selection aid, not a smear."""
    counsel: str
    firm: str | None
    side: Literal["appellant", "appellee"]
    n: int
    wins: int
    win_rate: float
    win_rate_ci95: CI95
    bench_hostile_mass_mean: float | None   # mean P(skepticism ≥ L3) toward this side in their arguments
    cases: list[str]                          # case numbers, for audit


class EntityDossier(TypedDict):
    entity_type: Literal["counsel", "firm"]
    court_id: str
    rows: list[CounselJudgeRow]
    floor_n: int


class VotingModelResult(TypedDict):
    """F25. Pure math; parameters are stated, nothing is inferred about a real panel."""
    model: Literal["condorcet_majority", "banzhaf"]
    params: dict[str, Any]
    result: dict[str, Any]
    note: str


# ---- registry: value_type string -> required keys --------------------------

REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "named_share[]": ("name", "count", "share"),
    "duration_days": ("n", "median", "p10", "p90", "from_event", "to_event"),
    "appeals_row": ("scope", "n", "affirmed", "reversed", "mixed", "reversal_rate", "reversal_rate_ci95"),
    "milestone_forecast[]": ("milestone", "from_event", "n", "p50_days", "p80_days", "p90_days"),
    "probability_card": ("outcome", "p", "base_rate", "n_calibration", "bin", "abstain", "why"),
    "decision_tree": ("target", "fit_on", "n", "root", "rules_text"),
    "counsel_judge_row[]": ("counsel", "side", "n", "wins", "win_rate", "win_rate_ci95"),
    "entity_dossier": ("entity_type", "court_id", "rows", "floor_n"),
    "voting_model_result": ("model", "params", "result"),
}


def validate(value_type: str, value: Any) -> list[str]:
    """Return a list of problems (empty = valid). Light on purpose."""
    req = REQUIRED_KEYS.get(value_type)
    if req is None:
        return []  # declared but not yet specified
    problems: list[str] = []
    items = value if value_type.endswith("[]") else [value]
    if value_type.endswith("[]") and not isinstance(value, list):
        return [f"{value_type} must be a list"]
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            problems.append(f"item {i} is not an object")
            continue
        for k in req:
            if k not in it:
                problems.append(f"item {i} missing '{k}'")
    return problems
