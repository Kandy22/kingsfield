#!/usr/bin/env python
"""
Figure 5 — Impact of keyboard layout and typing mistakes.

Panels:
  A — Keyboard Distance vs Confusion Rate (bar + dot overlay, n=19)
  B — K-means clustering of embeddings (hardcoded from original analysis)
  C — Keypress Intervals: before-keystroke interval (bar + dot overlay, n=24)
  D — CER for correct vs typing errors (bar + dot overlay, n=19)
      Both models derived from sentence-level prediction strings

Error bars = mean +/- SEM.
Statistics: two-sided Wilcoxon signed-rank test.

Usage:
    cd <this directory>
    python figure5_typing_analysis.py
"""

import difflib
import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import warnings

import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")
sns.set_theme(style="white")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.expanduser("~/brainai"))

PRED_CSV = os.path.join(DATA_ROOT, "data", "prediction_csv")
FULL_DF_POP = os.path.join(PRED_CSV, "full_df_max_population.csv")
RT_BEFORE_NON = os.path.join(DATA_ROOT, "data", "temp_data", "typing_errors", "rt_before_non_typos.npy")
RT_BEFORE_TYP = os.path.join(DATA_ROOT, "data", "temp_data", "typing_errors", "rt_before_typos.npy")
CONV_TRANS_CSV = os.path.join(PRED_CSV, "reviews_MEG_ConvTrans.csv")
CONV_CSV = os.path.join(PRED_CSV, "reviews_MEG_Conv.csv")

IDX_TO_NAME = {
    0: "S1", 1: "S2", 2: "S3", 3: "S4", 4: "S5", 5: "S6", 6: "S7",
    7: "S8", 8: "S9", 9: "S10", 10: "S11", 11: "S12", 12: "S14",
    13: "S15", 14: "S16", 15: "S17", 16: "S18", 17: "S19", 18: "S20",
    19: "S21", 20: "S22", 21: "S23", 22: "S24", 23: "S25",
}
MERGE = {"S18": "S1", "S14": "S4", "S10": "S5", "S21": "S5"}
EXCLUDE = {"S23"}

KEYBOARD_LAYOUT = {
    'q': (0, 0), 'w': (1, 0), 'e': (2, 0), 'r': (3, 0), 't': (4, 0),
    'y': (5, 0), 'u': (6, 0), 'i': (7, 0), 'o': (8, 0), 'p': (9, 0),
    'a': (0, 1), 's': (1, 1), 'd': (2, 1), 'f': (3, 1), 'g': (4, 1),
    'h': (5, 1), 'j': (6, 1), 'k': (7, 1), 'l': (8, 1),
    'z': (0, 2), 'x': (1, 2), 'c': (2, 2), 'v': (3, 2), 'b': (4, 2),
    'n': (5, 2), 'm': (6, 2),
}

COLORS = {'correct': '#3498DB', 'typo': '#e11230'}


def _apply_merge(df, col="subject"):
    df = df.copy()
    df["subj"] = df[col].map(IDX_TO_NAME)
    df["subj"] = df["subj"].replace(MERGE)
    return df[~df["subj"].isin(EXCLUDE)]


def classify_characters(label, prediction):
    """SequenceMatcher to classify typed chars as match/substitution/addition."""
    matcher = difflib.SequenceMatcher(None, label, prediction)
    result = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(["match"] * (j2 - j1))
        elif tag == "replace":
            result.extend(["substitution"] * (j2 - j1))
        elif tag == "insert":
            result.extend(["addition"] * (j2 - j1))
        elif tag == "delete":
            continue
    return result


def _keyboard_distance(k1, k2):
    p1 = KEYBOARD_LAYOUT.get(k1.lower())
    p2 = KEYBOARD_LAYOUT.get(k2.lower())
    if p1 is None or p2 is None:
        return None
    return int(np.ceil(np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)))


def _add_dots(ax, x_pos, vals, color="black", size=12, alpha=0.5):
    rng = np.random.default_rng(42)
    jitter = rng.uniform(-0.12, 0.12, len(vals))
    ax.scatter(x_pos + jitter, vals, color=color, s=size, alpha=alpha,
               zorder=5, edgecolors="white", linewidths=0.3)


def _sig_bracket(ax, x1, x2, y, p, dy=0.02):
    stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    if stars:
        ax.plot([x1, x1, x2, x2], [y, y + dy, y + dy, y], lw=1., c='k')
        ax.text((x1 + x2) / 2, y + dy, stars, fontsize=9, ha='center', va='bottom')


# ═══════════════════════════════════════════════════════════════════
# Panel A — Keyboard Distance vs Confusion Rate  (n=19 merged)
# ═══════════════════════════════════════════════════════════════════

def compute_panel_a():
    print("  Loading full_df_max_population for Panel A ...")
    cols = ["type", "subject", "button", "keystroke_prediction"]
    df = pd.read_csv(FULL_DF_POP, usecols=cols)
    df = _apply_merge(df)
    buttons = df[(df["type"] == "Button") & df["keystroke_prediction"].notna()]
    buttons = buttons[
        buttons["button"].str.isalpha() & buttons["keystroke_prediction"].str.isalpha()
    ]

    max_dist = 9
    subj_data = {}
    for subj, sdf in buttons.groupby("subj"):
        errors_by_dist = {}
        total_errors = 0
        wrong = sdf[sdf["button"] != sdf["keystroke_prediction"]]
        for _, row in wrong.iterrows():
            d = _keyboard_distance(row["button"], row["keystroke_prediction"])
            if d is not None and 1 <= d <= max_dist:
                errors_by_dist[d] = errors_by_dist.get(d, 0) + 1
                total_errors += 1
        if total_errors > 0:
            subj_data[subj] = np.array(
                [errors_by_dist.get(d, 0) / total_errors for d in range(1, max_dist + 1)]
            )

    matrix = np.array([subj_data[s] for s in sorted(subj_data)])
    return list(range(1, max_dist + 1)), matrix


def plot_panel_a(ax, dists, matrix):
    means = matrix.mean(axis=0)
    sems = matrix.std(axis=0) / np.sqrt(matrix.shape[0])
    x = np.arange(len(dists))

    ax.bar(x, means, color="#555555", width=0.75, zorder=2)
    for i in range(len(dists)):
        _add_dots(ax, x[i], matrix[:, i], color="black", size=8, alpha=0.35)

    ax.set_xticks(x)
    ax.set_xticklabels(dists)
    ax.set_xlabel("Keyboard Distance")
    ax.set_ylabel("Confusion Rate")

    flat_dists = np.repeat(np.arange(len(dists)), matrix.shape[0])
    flat_vals = matrix.T.flatten()
    r, p = stats.pearsonr(flat_dists, flat_vals)
    return {"r": r, "p": p, "n": matrix.shape[0]}


# ═══════════════════════════════════════════════════════════════════
# Panel B — K-means clustering (hardcoded)
# ═══════════════════════════════════════════════════════════════════

CLUSTER_2_IMG = os.path.join(DATA_ROOT, "data", "clusters", "2cluster.png")
CLUSTER_10_IMG = os.path.join(DATA_ROOT, "data", "clusters", "10cluster.png")


def plot_panel_b(ax_top, ax_bot):
    for ax, img_path in [(ax_top, CLUSTER_2_IMG), (ax_bot, CLUSTER_10_IMG)]:
        img = plt.imread(img_path)
        ax.imshow(img, aspect="equal")
        ax.axis("off")


# ═══════════════════════════════════════════════════════════════════
# Panel C — Keypress Intervals (merged to n=19)
# ═══════════════════════════════════════════════════════════════════

def _merge_array(arr):
    """Merge a 24-element per-subject array to 19 using IDX_TO_NAME/MERGE/EXCLUDE."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for idx in range(len(arr)):
        name = IDX_TO_NAME.get(idx)
        if name is None or name in EXCLUDE:
            continue
        merged_name = MERGE.get(name, name)
        if merged_name in EXCLUDE:
            continue
        buckets[merged_name].append(arr[idx])
    return np.array([np.mean(buckets[s]) for s in sorted(buckets)])


def compute_panel_c():
    rt_non_raw = np.load(RT_BEFORE_NON)
    rt_typ_raw = np.load(RT_BEFORE_TYP)
    return _merge_array(rt_non_raw), _merge_array(rt_typ_raw)


def plot_panel_c(ax, rt_non, rt_typ):
    n = len(rt_non)
    means = [rt_non.mean(), rt_typ.mean()]
    sems = [rt_non.std() / np.sqrt(n), rt_typ.std() / np.sqrt(n)]
    x = np.array([0, 1])

    ax.bar(x, means, color=[COLORS["correct"], COLORS["typo"]],
           width=0.7, zorder=2)
    _add_dots(ax, 0, rt_non, size=10, alpha=0.4)
    _add_dots(ax, 1, rt_typ, size=10, alpha=0.4)

    W, p = stats.wilcoxon(rt_non, rt_typ)
    _sig_bracket(ax, 0.15, 0.85, max(means) + 0.008, p, dy=0.003)

    ax.set_ylabel("Keypress intervals (s)")
    ax.set_ylim(0, 0.20)
    ax.set_yticks(np.arange(0, 0.21, 0.05))
    ax.set_xticks([])
    return {"W": W, "p": p, "n": n,
            "non_ms": rt_non.mean() * 1000, "typ_ms": rt_typ.mean() * 1000,
            "non_sem_ms": sems[0] * 1000, "typ_sem_ms": sems[1] * 1000}


# ═══════════════════════════════════════════════════════════════════
# Panel D — CER: correct vs typing errors
# ═══════════════════════════════════════════════════════════════════

def _per_char_cer_from_sentences(csv_path):
    """
    Derive per-character CER from sentence-level prediction strings.
    For each sentence, align Model Predictions with Typed Sentences
    character by character, then classify each typed character as
    match/substitution/addition via SequenceMatcher on True vs Typed.
    Returns per-subject CER arrays for correct vs typing-error chars.
    """
    df = pd.read_csv(csv_path)
    non_typo_cer = []
    typo_cer = []

    for subj in sorted(df["Subject"].unique()):
        sdf = df[df["Subject"] == subj]
        correct_errs, correct_n = 0, 0
        typo_errs, typo_n = 0, 0

        for _, row in sdf.iterrows():
            true_s = str(row["True Sentences"])
            typed_s = str(row["Typed Sentences"])
            pred_s = str(row["Model Predictions"])

            if len(typed_s) != len(pred_s):
                continue
            char_types = classify_characters(true_s, typed_s)
            if len(char_types) != len(typed_s):
                continue

            for i, ctype in enumerate(char_types):
                is_wrong = int(pred_s[i] != typed_s[i])
                if ctype == "match":
                    correct_n += 1
                    correct_errs += is_wrong
                else:
                    typo_n += 1
                    typo_errs += is_wrong

        if correct_n > 0:
            non_typo_cer.append(correct_errs / correct_n)
        if typo_n > 0:
            typo_cer.append(typo_errs / typo_n)

    return np.array(non_typo_cer), np.array(typo_cer)


def compute_panel_d():
    """
    Per-character CER derived from sentence-level prediction strings.
    Both Conv+Trans and Conv use the same methodology (n=19 each).
    """
    print("  Conv+Trans from reviews_MEG_ConvTrans.csv ...")
    ct_correct, ct_typo = _per_char_cer_from_sentences(CONV_TRANS_CSV)

    print("  Conv from reviews_MEG_Conv.csv ...")
    conv_correct, conv_typo = _per_char_cer_from_sentences(CONV_CSV)

    return ct_correct, ct_typo, conv_correct, conv_typo


def plot_panel_d(ax, ct_correct, ct_typo, conv_correct, conv_typo):
    data = [ct_correct, ct_typo, conv_correct, conv_typo]
    means = [a.mean() for a in data]
    sems = [a.std() / np.sqrt(len(a)) for a in data]
    x = np.array([0, 1, 2.5, 3.5])
    colors = [COLORS["correct"], COLORS["typo"], COLORS["correct"], COLORS["typo"]]

    ax.bar(x, means, color=colors, width=0.8, zorder=2)
    for arr, xi in zip(data, x):
        _add_dots(ax, xi, arr, size=8, alpha=0.35)

    for i in range(4):
        ax.text(x[i], 0.04, f"{means[i]:.2f}",
                ha="center", va="bottom", fontsize=7, color="white",
                fontweight="bold", zorder=6)

    ax.text(0.5, -0.06, "Conv+Trans", ha="center", va="top",
            fontsize=8, fontweight="bold", transform=ax.get_xaxis_transform())
    ax.text(3.0, -0.06, "Conv", ha="center", va="top",
            fontsize=8, fontweight="bold", transform=ax.get_xaxis_transform())

    ax.axhline(y=0.86, color="grey", linewidth=0.5, linestyle="--",
               alpha=0.4, zorder=0)

    results = {}
    for label, arr1, arr2, x1, x2 in [
        ("Conv+Trans", ct_correct, ct_typo, 0, 1),
        ("Conv", conv_correct, conv_typo, 2.5, 3.5),
    ]:
        n_paired = min(len(arr1), len(arr2))
        W, p = stats.wilcoxon(arr1[:n_paired], arr2[:n_paired])
        results[label] = {"W": W, "p": p, "n": n_paired}
        _sig_bracket(ax, x1 + 0.1, x2 - 0.1, 0.88, p, dy=0.02)

    ax.set_ylabel("CER")
    ax.set_ylim(0, 1.05)
    ax.set_yticks(np.arange(0, 1.1, 0.2))
    ax.set_xticks([])
    return results


# ═══════════════════════════════════════════════════════════════════
# Source Data export
# ═══════════════════════════════════════════════════════════════════

def _export_source_data(dists, kb_matrix, rt_non, rt_typ,
                        ct_c, ct_t, conv_c, conv_t):
    out = os.path.join(DATA_ROOT, "data", "fig5_source_data.xlsx")

    sorted_subjs_a = sorted({
        s for s in set(IDX_TO_NAME.values())
        if MERGE.get(s, s) not in EXCLUDE and s not in EXCLUDE
    })
    merged_a = sorted({MERGE.get(s, s) for s in sorted_subjs_a})

    df_a = pd.DataFrame(kb_matrix, columns=[f"Distance {d}" for d in dists])
    df_a.insert(0, "Participant", merged_a[:kb_matrix.shape[0]])

    df_c = pd.DataFrame({
        "Participant": merged_a[:len(rt_non)],
        "Correct keystrokes (s)": rt_non,
        "Typing errors (s)": rt_typ,
    })

    csv_ct = pd.read_csv(CONV_TRANS_CSV)
    subjs_ct = sorted(csv_ct["Subject"].unique())
    df_d_ct = pd.DataFrame({
        "Participant": [f"S{int(s)}" for s in subjs_ct],
        "Correct CER": ct_c,
        "Typing Error CER": ct_t,
    })

    csv_conv = pd.read_csv(CONV_CSV)
    subjs_conv = sorted(csv_conv["Subject"].unique())
    df_d_conv = pd.DataFrame({
        "Participant": [f"S{int(s)}" for s in subjs_conv],
        "Correct CER": conv_c,
        "Typing Error CER": conv_t,
    })

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="Fig 5A - Keyboard Distance", index=False)
        df_c.to_excel(writer, sheet_name="Fig 5C - Keypress Intervals", index=False)
        df_d_ct.to_excel(writer, sheet_name="Fig 5D - CER Conv+Trans", index=False)
        df_d_conv.to_excel(writer, sheet_name="Fig 5D - CER Conv", index=False)

    print(f"\n  -> {out}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Figure 5 — Keyboard layout and typing mistakes")
    print("=" * 60)

    print("\n[A] Keyboard distance ...")
    dists, kb_matrix = compute_panel_a()
    print(f"    n = {kb_matrix.shape[0]}")

    print("\n[B] K-means clustering (hardcoded)")

    print("\n[C] Keypress intervals ...")
    rt_non, rt_typ = compute_panel_c()
    print(f"    n = {len(rt_non)}")

    print("\n[D] Typing errors CER ...")
    ct_c, ct_t, conv_c, conv_t = compute_panel_d()
    print(f"    Conv+Trans: n={len(ct_c)},  correct={ct_c.mean():.3f}  typo={ct_t.mean():.3f}")
    print(f"    Conv:       n={len(conv_c)}, correct={conv_c.mean():.3f}  typo={conv_t.mean():.3f}")

    # ── Plot ──
    print("\nPlotting ...")
    fig = plt.figure(figsize=(14, 3.0))
    gs = fig.add_gridspec(2, 4, width_ratios=[1.1, 1.4, 0.8, 1.1],
                          height_ratios=[1, 1], hspace=0.45, wspace=0.5,
                          top=0.88, bottom=0.16, left=0.05, right=0.98)

    ax_a = fig.add_subplot(gs[:, 0])
    ax_b_top = fig.add_subplot(gs[0, 1])
    ax_b_bot = fig.add_subplot(gs[1, 1])
    ax_c = fig.add_subplot(gs[:, 2])
    ax_d = fig.add_subplot(gs[:, 3])

    a_stats = plot_panel_a(ax_a, dists, kb_matrix)
    plot_panel_b(ax_b_top, ax_b_bot)
    c_stats = plot_panel_c(ax_c, rt_non, rt_typ)
    d_stats = plot_panel_d(ax_d, ct_c, ct_t, conv_c, conv_t)

    fig.canvas.draw()
    pos_a = ax_a.get_position()
    pos_b = ax_b_top.get_position()
    gap = pos_b.x0 - pos_a.x1
    shift = gap * 0.7
    ax_a.set_position([pos_a.x0 + shift, pos_a.y0, pos_a.width, pos_a.height])

    for ax in [ax_a, ax_c, ax_d]:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    label_fs = 13
    label_y = 0.99
    for ax, letter in zip([ax_a, ax_b_top, ax_c, ax_d], "ABCD"):
        bb = ax.get_position()
        fig.text(bb.x0 - 0.02, label_y, letter,
                 va="top", ha="left", weight="bold", fontsize=label_fs,
                 transform=fig.transFigure)

    from matplotlib.patches import Patch
    mid_x = (ax_c.get_position().x0 + ax_d.get_position().x1) / 2
    leg = fig.legend(
        handles=[Patch(facecolor=COLORS["correct"], label="Correct Characters"),
                 Patch(facecolor=COLORS["typo"], label="Typing Mistakes")],
        loc="upper center", ncol=2, fontsize=10,
        frameon=True, edgecolor="lightgrey", fancybox=True,
        framealpha=1.0, facecolor="white",
        bbox_to_anchor=(mid_x, 0.10), bbox_transform=fig.transFigure,
    )
    leg.get_frame().set_linewidth(1.0)

    out_pdf = os.path.join(SCRIPT_DIR, "figure5.pdf")
    out_png = os.path.join(SCRIPT_DIR, "figure5.png")
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, bbox_inches="tight", dpi=300)
    print(f"\n  -> {out_pdf}")
    print(f"  -> {out_png}")

    # ── Source Data ──
    _export_source_data(dists, kb_matrix, rt_non, rt_typ,
                        ct_c, ct_t, conv_c, conv_t)

    # ── Statistics summary ──
    print("\n" + "=" * 60)
    print("STATISTICS SUMMARY")
    print("=" * 60)

    print(f"\nPanel A (n={a_stats['n']}): Pearson r={a_stats['r']:.4f}, p={a_stats['p']:.2e}")

    print(f"\nPanel C (n={c_stats['n']}):")
    print(f"  Correct: {c_stats['non_ms']:.0f} +/- {c_stats['non_sem_ms']:.0f} ms")
    print(f"  Typing errors: {c_stats['typ_ms']:.0f} +/- {c_stats['typ_sem_ms']:.0f} ms")
    print(f"  Wilcoxon W={c_stats['W']:.0f}, p={c_stats['p']:.2e}")

    print(f"\nPanel D:")
    for model, s in d_stats.items():
        print(f"  {model}: n={s['n']} paired, W={s['W']:.0f}, p={s['p']:.2e}")


if __name__ == "__main__":
    main()
