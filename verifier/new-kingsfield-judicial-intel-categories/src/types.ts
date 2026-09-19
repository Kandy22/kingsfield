/** Canonical types for the 3 / 6 / 29 Kingsfield judicial-intelligence catalog. */

export type TopId = "T1" | "T2" | "T3";
export type MainId = "M1" | "M2" | "M3" | "M4" | "M5" | "M6";
export type FactualId =
  | "F01" | "F02" | "F03" | "F04" | "F05" | "F06" | "F07" | "F08" | "F09" | "F10"
  | "F11" | "F12" | "F13" | "F14" | "F15" | "F16" | "F17" | "F18" | "F19" | "F20"
  | "F21" | "F22" | "F23" | "F24" | "F25" | "F26" | "F27" | "F28" | "F29";

export type CategoryKind =
  | "profile"
  | "metric"
  | "distribution"
  | "rate_table"
  | "holding_index"
  | "money_table"
  | "forecast"
  | "model";

export type JevQuestionType = "noul" | "choice" | "score";

export interface JevHint {
  role:
    | "none"
    | "classify_incoming"
    | "score_outlier"
    | "verify_against_opinion"
    | "match_entity"
    | "score_rule_fit"
    | "rank_neighbor"
    | "calibrate_or_abstain"
    | "choose_forum";
  question_type?: JevQuestionType;
  note?: string;
}

export interface TopCategory {
  id: TopId;
  slug: string;
  name: string;
  modeled_on: string;
  blurb: string;
}

export interface MainCategory {
  id: MainId;
  slug: string;
  name: string;
  top: TopId | TopId[];
  blurb: string;
}

export interface FactualCategory {
  id: FactualId;
  code: string;
  name: string;
  top: TopId;
  main: MainId;
  source_pattern: string;
  kind: CategoryKind;
  sentence: string;
  value_type: string;
  jev: JevHint;
}

export interface Catalog {
  version: string;
  updated: string;
  product: string;
  disclaimer: string;
  counts: { top: 3; main: 6; factual: 29 };
  top: TopCategory[];
  main: MainCategory[];
  factual: FactualCategory[];
}

/** Payload shape Kingsfield stores per judge snapshot. */
export interface JudgeIntelSnapshot {
  judge_id: string;
  court_id: string;
  as_of: string;
  fields: Partial<Record<FactualId, unknown>>;
  provenance: Partial<Record<FactualId, { source: string; collected_at: string }>>;
}


/* ---- value_type schemas (mirror of src/value_types.py) ------------------- */

export interface NamedShare { name: string; count: number; share: number }
export interface DurationDays { n: number; median: number; mean: number; p10: number; p90: number; from_event: string; to_event: string }
export interface CI95 { lo: number; hi: number; method: "wilson" }
export interface AppealsYearRow { year: number; n: number; reversal_rate: number }
export interface AppealsRow {
  scope: "court" | "appellate_judge_panels" | "trial_judge_trail";
  n: number; affirmed: number; reversed: number; mixed: number; other: number;
  reversal_rate: number | null; reversal_rate_ci95: CI95;
  pca_share?: number; argued_share?: number; by_year?: AppealsYearRow[];
}
export interface MilestoneForecast { milestone: string; from_event: string; n: number; p50_days: number; p80_days: number; p90_days: number; basis: string }
export interface ProbabilityCard {
  outcome: string; p: number | null; base_rate: number; n_calibration: number; bin: string;
  abstain: boolean; why: string; inputs: Record<string, unknown>;
}
export interface DecisionLeaf { leaf: true; n: number; p_affirm: number | null; label: string }
export interface DecisionNode { leaf: false; feature: string; op: ">=" | "<=" | "=="; threshold: number | string; left: DecisionNode | DecisionLeaf; right: DecisionNode | DecisionLeaf }
export interface DecisionTree { target: string; fit_on: string; n: number; root: DecisionNode | DecisionLeaf; rules_text: string[] }
export interface CounselJudgeRow {
  counsel: string; firm: string | null; side: "appellant" | "appellee"; n: number; wins: number;
  win_rate: number; win_rate_ci95: CI95; bench_hostile_mass_mean: number | null; cases: string[];
}
export interface EntityDossier { entity_type: "counsel" | "firm"; court_id: string; rows: CounselJudgeRow[]; floor_n: number }
export interface VotingModelResult { model: "condorcet_majority" | "banzhaf"; params: Record<string, unknown>; result: Record<string, unknown>; note: string }
