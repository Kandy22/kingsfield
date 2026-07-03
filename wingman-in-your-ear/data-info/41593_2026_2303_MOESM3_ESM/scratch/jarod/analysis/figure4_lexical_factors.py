#!/usr/bin/env python
"""
Figure 4 — Impact of lexical factors on decoding performance.

- n=19 MEG subjects (merged subjects, S23 excluded)
- Panel A: POS CER bar chart with individual data-point overlay
- Panel B: Word-frequency CER (OOV + quartiles)
- Panel C: Character frequency vs CER scatter with regression

Usage:
    python figure4_lexical_factors.py
"""

import os
import warnings

import Levenshtein as lev
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")
sns.set(style="white")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.expanduser("~/brainai"))

FULL_DF = os.path.join(DATA_ROOT, "data", "prediction_csv", "full_df_max_population.csv")
POS_CSV = os.path.join(DATA_ROOT, "data", "temp_data", "POS", "part_of_speech_character.csv")

# Subject index (factorized in full_df) → original Pinet2024Meg name
IDX_TO_NAME = {
    0: "S1", 1: "S2", 2: "S3", 3: "S4", 4: "S5", 5: "S6", 6: "S7",
    7: "S8", 8: "S9", 9: "S10", 10: "S11", 11: "S12", 12: "S14",
    13: "S15", 14: "S16", 15: "S17", 16: "S18", 17: "S19", 18: "S20",
    19: "S21", 20: "S22", 21: "S23", 22: "S24", 23: "S25",
}
MERGE = {"S18": "S1", "S14": "S4", "S10": "S5", "S21": "S5"}
EXCLUDE = {"S23"}

CER_CHANCE = 0.868
WER_CHANCE = 0.893


def _apply_merge(df, subject_col="subject"):
    df = df.copy()
    df["subj"] = df[subject_col].map(IDX_TO_NAME)
    df["subj"] = df["subj"].replace(MERGE)
    return df[~df["subj"].isin(EXCLUDE)]


def _stars(p):
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


# ═══════════════════════════════════════════════════════════════════
# Panel A — Part-of-speech CER (from pre-computed CSV, approx merge)
# ═══════════════════════════════════════════════════════════════════

def compute_panel_a():
    df = pd.read_csv(POS_CSV, index_col=0)
    df = _apply_merge(df)
    result = df.groupby(["subj", "pos"])["mean"].mean().reset_index()
    result.columns = ["subj", "pos", "cer"]
    return result


def plot_panel_a(ax, data):
    palette = sns.color_palette("deep", 5)
    pos_order = ["ADJ", "ADP", "DET", "NOUN", "VERB"]

    grp = data.groupby("pos")["cer"].agg(["mean", "std", "count"]).reindex(pos_order)
    grp["sem"] = grp["std"] / np.sqrt(grp["count"])

    x = np.arange(len(pos_order))
    ax.bar(x, grp["mean"], color=palette, zorder=2, width=0.7)

    rng = np.random.default_rng(42)
    for i, pos in enumerate(pos_order):
        vals = data[data["pos"] == pos]["cer"].values
        jitter = rng.uniform(-0.12, 0.12, len(vals))
        ax.scatter(x[i] + jitter, vals, color="black", s=18, alpha=0.45,
                   zorder=3, edgecolors="white", linewidths=0.4)

    ax.axhline(CER_CHANCE, color="gray", linewidth=0.5)

    stat_results = {}
    for i, pos in enumerate(pos_order):
        vals = data[data["pos"] == pos]["cer"].values
        W, p = stats.wilcoxon(vals - CER_CHANCE)
        stat_results[pos] = {"n": len(vals), "W": W, "p": p}
        s = _stars(p)
        if s:
            ax.text(i, CER_CHANCE - 0.06,
                    s, ha="center", va="top", fontsize=8)

    ax.set_ylabel("CER")
    ax.set_xticks(x)
    ax.set_xticklabels(pos_order, rotation=30)
    ax.set_yticks(np.arange(0, 1.0, 0.4))
    return stat_results


# ═══════════════════════════════════════════════════════════════════
# Data loading (shared by panels B & C)
# ═══════════════════════════════════════════════════════════════════

def load_buttons(merge=True):
    """Load full_df Button rows. If merge=True, apply subject merge to n=19."""
    print("  Loading full_df_max_population.csv …")
    cols = ["type", "subject", "split", "button",
            "keystroke_prediction", "text", "sentence", "sentence_UID"]
    df = pd.read_csv(FULL_DF, usecols=cols)
    if merge:
        df = _apply_merge(df)
    else:
        df = df.copy()
        df["subj"] = df["subject"].map(IDX_TO_NAME)

    buttons = df[df["type"] == "Button"].copy()
    buttons = buttons[(buttons["text"] != "FAILED") & buttons["text"].notna()]
    buttons = buttons.dropna(subset=["keystroke_prediction"])
    buttons["error"] = (buttons["button"] != buttons["keystroke_prediction"]).astype(int)
    return buttons


# ═══════════════════════════════════════════════════════════════════
# Panel B — Word-frequency CER (n=19, same merge as other panels)
# ═══════════════════════════════════════════════════════════════════

def compute_panel_b(all_buttons):
    """Word-frequency CER with merged subjects (n=19)."""
    train = all_buttons[all_buttons["split"] == "train"]
    test = all_buttons[all_buttons["split"] == "test"].copy()

    print("  Computing word-level CER (Levenshtein) …")
    word_level = (
        test.groupby(["sentence_UID", "text", "subj"])["keystroke_prediction"]
        .apply(lambda x: "".join(x))
        .reset_index(name="word_pred")
    )
    word_level["word_cer"] = word_level.apply(
        lambda r: lev.distance(r["text"], r["word_pred"]) / max(len(r["text"]), 1),
        axis=1,
    )

    train_words = set(train["text"].unique())
    test_words = set(word_level["text"].unique())
    oov_words = test_words - train_words
    in_words = test_words & train_words

    in_train = train[train["text"].isin(in_words)]
    word_freq = in_train.groupby("text").size()
    q25, q50, q75 = np.percentile(word_freq.values, [25, 50, 75])

    quartile_bins = {
        "Rare": word_freq[word_freq <= q25].index,
        "Q2": word_freq[(word_freq > q25) & (word_freq <= q50)].index,
        "Q3": word_freq[(word_freq > q50) & (word_freq <= q75)].index,
        "Frequent": word_freq[word_freq > q75].index,
    }

    groups = {}
    oov_df = word_level[word_level["text"].isin(oov_words)]
    groups["OOV"] = oov_df.groupby("subj")["word_cer"].mean()

    for label, words in quartile_bins.items():
        qdf = word_level[word_level["text"].isin(words)]
        groups[label] = qdf.groupby("subj")["word_cer"].mean()

    n_subj = word_level["subj"].nunique()
    return groups, n_subj


def plot_panel_b(ax, groups, n_subj):
    """Original style: line plot with SEM, stars, no individual dots."""
    order = ["OOV", "Rare", "Q2", "Q3", "Frequent"]
    means = [groups[k].mean() for k in order]
    sems = [groups[k].std() / np.sqrt(len(groups[k])) for k in order]

    x = np.arange(len(order))
    ax.plot(x, means, "o-", color="grey", markersize=9, zorder=4)
    ax.errorbar(x, means, yerr=sems, fmt="none", c="black", capsize=2, zorder=5)

    ax.axhline(WER_CHANCE, color="gray", linewidth=0.5)

    stat_results = {}
    for i, k in enumerate(order):
        vals = groups[k].values
        if np.all(vals >= WER_CHANCE):
            stat_results[k] = {"n": len(vals), "W": None, "p": 1.0}
            continue
        W, p = stats.wilcoxon(vals - WER_CHANCE, alternative="less")
        stat_results[k] = {"n": len(vals), "W": W, "p": p}
        s = _stars(p)
        if s and means[i] < WER_CHANCE:
            ax.text(i, means[i] + sems[i] + 0.01, s,
                    ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Word Frequency Quartile")
    ax.set_xticks(x)
    ax.set_xticklabels(["OOV", "Rare", "", "", "Frequent"])
    ax.set_yticks(np.arange(0, 1.1, 0.4))
    return stat_results


# ═══════════════════════════════════════════════════════════════════
# Panel C — Character frequency vs CER scatter
# ═══════════════════════════════════════════════════════════════════

def compute_panel_c(test_buttons):
    freq_per_subj = test_buttons.groupby(["button", "subj"]).size().reset_index(name="freq")
    mean_freq = freq_per_subj.groupby("button")["freq"].mean()
    mean_err = test_buttons.groupby("button")["error"].mean()

    cs = pd.DataFrame({
        "Character": mean_freq.index,
        "Frequency": mean_freq.values,
        "Error Rate": mean_err.values,
    })
    cs = cs[~cs["Character"].isin(["@", "9"])]
    space_freq = cs.loc[cs["Character"] == " ", "Frequency"].values[0]
    cs["Normalized Frequency"] = cs["Frequency"] / space_freq
    cs.loc[cs["Character"] == " ", "Character"] = "space"
    return cs


CHAR_OFFSETS = {
    "space": (-0.30, -0.12),
    "h": (-0.03, 0.10),
    "u": (-0.03, 0.05),
    "x": (-0.04, -0.16),
    "o": (-0.03, 0.10),
    "y": (0.01, -0.10),
    "t": (0.01, -0.15),
    "m": (0.01, -0.01),
    "c": (0.01, -0.01),
    "w": (0.03, 0.05),
}
CHAR_SKIP = {"z", "k", "f", "q", "g"}


def plot_panel_c(ax, data):
    ax.scatter(data["Normalized Frequency"], data["Error Rate"],
               color="black", s=50, zorder=3, edgecolors="none")

    sns.regplot(data=data, x="Normalized Frequency", y="Error Rate",
                scatter=False, line_kws={"linewidth": 0.5}, ci=95,
                ax=ax, color="grey")

    ax.axhline(CER_CHANCE, color="gray", linewidth=0.5)

    for _, row in data.iterrows():
        ch = row["Character"]
        if ch in CHAR_SKIP:
            continue
        dx, dy = CHAR_OFFSETS.get(ch, (0.01, -0.10))
        ax.text(row["Normalized Frequency"] + dx,
                row["Error Rate"] + dy, ch,
                fontsize=12, color="black", zorder=5)

    r, p = stats.pearsonr(data["Normalized Frequency"], data["Error Rate"])

    ax.set_xlabel("Normalized Frequency")
    ax.set_ylabel("")
    ax.set_yticks(np.arange(0, 1.1, 0.4))
    return r, p, len(data)


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Figure 4 — Lexical factors (n = 19 MEG)")
    print("=" * 60)

    # Panel A
    print("\n[A] POS CER …")
    pos_data = compute_panel_a()
    n_a = pos_data["subj"].nunique()
    print(f"    n = {n_a} participants")

    # Load merged buttons (n=19) — shared by Panel B and C
    print("\n[B/C] Loading event data (19 subjects, merged) …")
    all_buttons_19 = load_buttons(merge=True)
    print(f"    n = {all_buttons_19['subj'].nunique()} participants")

    print("\n[B] Word-frequency CER …")
    word_freq_groups, n_b = compute_panel_b(all_buttons_19)

    # Panel C
    test_buttons = all_buttons_19[all_buttons_19["split"] == "test"].copy()
    n_c = test_buttons["subj"].nunique()
    print(f"\n[C] n = {n_c} participants (test set)")

    print("\n[C] Character-frequency CER …")
    char_data = compute_panel_c(test_buttons)

    # ── Plot ──
    print("\nPlotting …")
    fig, axes = plt.subplots(1, 3, figsize=(10, 3))

    a_stats = plot_panel_a(axes[0], pos_data)
    b_stats = plot_panel_b(axes[1], word_freq_groups, n_b)
    c_r, c_p, c_n = plot_panel_c(axes[2], char_data)

    for i, letter in enumerate("ABC"):
        axes[i].text(-0.02, 1.2, letter, transform=axes[i].transAxes,
                     va="top", ha="right", weight="bold")
        axes[i].spines["top"].set_visible(False)
        axes[i].spines["right"].set_visible(False)

    plt.tight_layout()

    out_pdf = os.path.join(SCRIPT_DIR, "figure4.pdf")
    out_png = os.path.join(SCRIPT_DIR, "figure4.png")
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, bbox_inches="tight", dpi=150)
    print(f"\n  → {out_pdf}")
    print(f"  → {out_png}")

    # ── Statistics summary ──
    print("\n" + "=" * 60)
    print("STATISTICS")
    print("=" * 60)

    print("\n— Panel A: POS CER (vs chance = {:.3f}) —".format(CER_CHANCE))
    for pos in ["ADJ", "ADP", "DET", "NOUN", "VERB"]:
        s = a_stats[pos]
        print(f"  {pos:5s}  n={s['n']:2d}  W={s['W']:.1f}  p={s['p']:.2e}")

    print("\n— Panel B: Word-frequency CER (vs chance = {:.3f}) —".format(WER_CHANCE))
    for k in ["OOV", "Rare", "Q2", "Q3", "Frequent"]:
        s = b_stats[k]
        w_str = f"{s['W']:.1f}" if s["W"] is not None else "n/a"
        print(f"  {k:10s}  n={s['n']:2d}  W={w_str}  p={s['p']:.2e}")
    # Rare vs Frequent comparison
    rare_vals = word_freq_groups["Rare"].values
    freq_vals = word_freq_groups["Frequent"].values
    n_paired = min(len(rare_vals), len(freq_vals))
    if n_paired >= 6:
        W_rf, p_rf = stats.wilcoxon(rare_vals[:n_paired], freq_vals[:n_paired])
        print(f"  Rare vs Frequent (paired Wilcoxon): W={W_rf:.1f}, p={p_rf:.2e}")

    print(f"\n— Panel C: Character frequency —")
    print(f"  Pearson r = {c_r:.4f}, p = {c_p:.2e}, n = {c_n} characters")


if __name__ == "__main__":
    main()
