#!/usr/bin/env python
"""
Figure 3 — Sentence-level performance for best, median, and worst MEG subjects.

Loads a pre-computed 3D array of per-sentence, per-repetition CER values
and plots the CER distribution sorted by difficulty for three representative
subjects (best, median, worst by mean CER).

Usage:
    python figure3_sentences.py
"""

import os

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

sns.set_theme(style="white")

DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.expanduser("~/brainai"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ARRAY_PATH = os.path.join(DATA_ROOT, "data", "temp_data", "3D_array_for_figure_2.3.npy")


def select_subjects(results):
    """Select best, median, worst subjects by mean CER."""
    subject_means = np.nanmean(np.nanmean(results, axis=2), axis=1)
    ranking = np.argsort(subject_means)
    best = ranking[0]
    median = ranking[len(ranking) // 2]
    worst = ranking[-1]
    return best, median, worst, subject_means


def plot_subject_panel(ax, subject_results, title, color):
    """Plot per-sentence CER with SEM error bars, sorted by ascending CER."""
    means = np.nanmean(subject_results, axis=1)
    n_reps = np.sum(~np.isnan(subject_results), axis=1)
    sems = np.nanstd(subject_results, axis=1) / np.sqrt(np.maximum(n_reps, 1))

    valid = ~np.isnan(means)
    means, sems = means[valid], sems[valid]

    sorted_idx = np.argsort(means)
    means = means[sorted_idx]
    sems = sems[sorted_idx]

    x = np.arange(len(means))
    ax.errorbar(x, means, yerr=sems, fmt="none", ecolor="lightgrey",
                elinewidth=0.5, capsize=0, zorder=1)
    ax.scatter(x, means, c=color, s=8, zorder=2, edgecolors="none")

    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_ylim(-0.02, 0.92)
    ax.set_yticks(np.arange(0, 1.0, 0.2))
    ax.set_xlabel("Sentences (sorted by CER)")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    return means, sems


def main():
    print("=" * 60)
    print("Figure 3 — Sentence-level performance")
    print("=" * 60)

    results = np.load(ARRAY_PATH)
    n_subjects, n_sentences, n_reps = results.shape
    print(f"  Array shape: {results.shape}  ({n_subjects} subjects, "
          f"{n_sentences} sentences, {n_reps} repetitions)")

    best, median, worst, subject_means = select_subjects(results)
    print(f"  Best subject:   idx={best}  mean CER={subject_means[best]:.3f}")
    print(f"  Median subject: idx={median}  mean CER={subject_means[median]:.3f}")
    print(f"  Worst subject:  idx={worst}  mean CER={subject_means[worst]:.3f}")

    green = sns.color_palette("Greens", 10)[7]

    fig, axes = plt.subplots(1, 3, figsize=(14, 3), sharey=True)

    plot_subject_panel(axes[0], results[best], "Best MEG Subject", green)
    axes[0].set_ylabel("CER")
    plot_subject_panel(axes[1], results[median], "Median MEG Subject", green)
    plot_subject_panel(axes[2], results[worst], "Worst MEG Subject", green)

    for i, letter in enumerate("ABC"):
        axes[i].text(-0.02, 1.15, letter, transform=axes[i].transAxes,
                     va="top", ha="right", weight="bold", fontsize=13)

    plt.tight_layout()
    out = os.path.join(SCRIPT_DIR, "figure3_sentences.pdf")
    fig.savefig(out, bbox_inches="tight")
    print(f"\n  -> {out}")


if __name__ == "__main__":
    main()
