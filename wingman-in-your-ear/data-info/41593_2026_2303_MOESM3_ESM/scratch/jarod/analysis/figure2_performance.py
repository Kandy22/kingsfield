#!/usr/bin/env python
"""
Figure 2 — Decoding performance across models and modalities.

Compares Linear, EEGNet, Conv (BM), Conv+Trans (BM+T), and Brain2Qwerty
across EEG and MEG on two metrics:
  Row A: HER (Hands Error Rate = 1 - max class accuracy)
  Row B: CER (Character Error Rate at sentence level)

Statistics: two-sided Wilcoxon signed-rank tests between consecutive models.

Usage:
    python figure2_performance.py
"""

import os

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from scipy.stats import wilcoxon

sns.set_theme(style="white")

DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.expanduser("~/brainai"))
TEMP = os.path.join(DATA_ROOT, "data", "temp_data")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_NAMES = ["Linear", "EEGNet", "Conv", "Conv\n+Trans", "Brain2\nQwerty"]


def _stars(p):
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


def _load_her(modality):
    """Load Hands Error Rate arrays (1 - max class accuracy per subject)."""
    tag = modality.upper()
    linear = np.load(os.path.join(TEMP, f"accuracies_{modality.lower()}_handsaccuracy.npy"))
    linear_her = 1.0 - np.max(linear, axis=1)
    eegnet = 1.0 - np.load(os.path.join(TEMP, f"eegnet_accuracies_hands_{tag}.npy"))
    bm = 1.0 - np.load(os.path.join(TEMP, f"no_transformer_accuracies_hands_{tag}.npy"))
    bm_t = 1.0 - np.load(os.path.join(TEMP, f"predictions_accuracies_hands_{tag}.npy"))
    ours = 1.0 - np.load(os.path.join(TEMP, f"lm_predictions_accuracies_hands_{tag}.npy"))
    return [linear_her, eegnet, bm, bm_t, ours]


def _load_cer(modality):
    """Load sentence-level CER arrays."""
    tag = modality.upper()
    return [
        np.load(os.path.join(TEMP, f"SentenceLevel_{tag}_Linear_CER.npy")),
        np.load(os.path.join(TEMP, f"SentenceLevel_{tag}_EEGNet_CER.npy")),
        np.load(os.path.join(TEMP, f"SentenceLevel_{tag}_BM_CER.npy")),
        np.load(os.path.join(TEMP, f"SentenceLevel_{tag}_BM+T_CER.npy")),
        np.load(os.path.join(TEMP, f"SentenceLevel_{tag}_Ours_CER.npy")),
    ]


def _plot_panel(ax, arrays, palette, ylabel, show_yaxis=True):
    """Strip plot with mean bars and significance brackets."""
    n_models = len(arrays)
    x_positions = np.arange(n_models)

    for i, arr in enumerate(arrays):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(arr))
        ax.scatter(x_positions[i] + jitter, arr, color=palette[i],
                   s=20, alpha=0.6, zorder=3, edgecolors="white", linewidths=0.3)
        ax.hlines(arr.mean(), x_positions[i] - 0.3, x_positions[i] + 0.3,
                  color="black", linewidth=1.5, zorder=4)

    p_values = []
    for i in range(n_models - 1):
        n_paired = min(len(arrays[i]), len(arrays[i + 1]))
        _, p = wilcoxon(arrays[i][:n_paired], arrays[i + 1][:n_paired])
        p_values.append(p)

    y_max = max(arr.max() for arr in arrays)
    for i, p in enumerate(p_values):
        s = _stars(p)
        if s:
            y = y_max + 0.03 + i * 0.05
            x1, x2 = x_positions[i], x_positions[i + 1]
            ax.plot([x1, x1, x2, x2], [y, y + 0.01, y + 0.01, y], lw=0.8, c='k')
            ax.text((x1 + x2) / 2, y + 0.012, s, ha="center", va="bottom", fontsize=7)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(MODEL_NAMES, fontsize=7)
    ax.set_ylabel(ylabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if not show_yaxis:
        ax.set_ylabel("")
        ax.tick_params(axis="y", labelleft=False)

    return p_values


def main():
    print("=" * 60)
    print("Figure 2 — Decoding performance")
    print("=" * 60)

    her_eeg = _load_her("EEG")
    her_meg = _load_her("MEG")
    cer_eeg = _load_cer("EEG")
    cer_meg = _load_cer("MEG")

    eeg_palette = sns.color_palette("Blues", 7)[2:]
    meg_palette = sns.color_palette("Greens", 7)[2:]

    fig, axes = plt.subplots(2, 2, figsize=(10, 6), sharex=True)

    print("\n[A1] EEG HER")
    p = _plot_panel(axes[0, 0], her_eeg, eeg_palette, "HER")
    for i, name in enumerate(["Lin-EEG", "EEG-BM", "BM-BM+T", "BM+T-Ours"]):
        print(f"  {name}: p={p[i]:.2e} {_stars(p[i])}")
    print(f"  n = {len(her_eeg[0])}")

    print("\n[A2] MEG HER")
    p = _plot_panel(axes[0, 1], her_meg, meg_palette, "HER", show_yaxis=False)
    for i, name in enumerate(["Lin-EEG", "EEG-BM", "BM-BM+T", "BM+T-Ours"]):
        print(f"  {name}: p={p[i]:.2e} {_stars(p[i])}")
    print(f"  n = {len(her_meg[0])}")

    print("\n[B1] EEG CER")
    p = _plot_panel(axes[1, 0], cer_eeg, eeg_palette, "CER")
    for i, name in enumerate(["Lin-EEG", "EEG-BM", "BM-BM+T", "BM+T-Ours"]):
        print(f"  {name}: p={p[i]:.2e} {_stars(p[i])}")
    print(f"  n = {len(cer_eeg[0])}")

    print("\n[B2] MEG CER")
    p = _plot_panel(axes[1, 1], cer_meg, meg_palette, "CER", show_yaxis=False)
    for i, name in enumerate(["Lin-EEG", "EEG-BM", "BM-BM+T", "BM+T-Ours"]):
        print(f"  {name}: p={p[i]:.2e} {_stars(p[i])}")
    print(f"  n = {len(cer_meg[0])}")

    axes[0, 0].set_title("EEG", fontsize=12, fontweight="bold")
    axes[0, 1].set_title("MEG", fontsize=12, fontweight="bold")

    plt.tight_layout()
    out = os.path.join(SCRIPT_DIR, "figure2_performance.pdf")
    fig.savefig(out, bbox_inches="tight")
    print(f"\n  -> {out}")


if __name__ == "__main__":
    main()
