# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Evaluation metrics.
"""

# pylint: disable=attribute-defined-outside-init

import typing as tp
from collections import defaultdict

import numpy as np
import torch
import torchmetrics


class OnlinePearsonCorr(torchmetrics.regression.PearsonCorrCoef):
    """
    Online Pearson correlation coefficient.

    This class computes the Pearson correlation coefficient in an online fashion,
    updating the metric with each new batch of predictions and targets.

    Parameters
    ----------
    dim : int
        The dimension along which to compute the correlation coefficient.
    reduction : {"mean", "sum", "none"}, optional
        Specifies how to reduce the computed correlation coefficients. Defaults to "mean".

    Notes
    -----
    - This implementation does not support varying the size of the input tensors
    along the specified dimension (`dim`). For example, it will not work with
    variable sequence lengths (when dim = 1).
    """

    def __init__(
        self,
        dim: int,
        reduction: tp.Literal["mean", "sum", "none"] | None = "mean",
    ):

        super().__init__()
        self.dim = dim
        self.reduction = reduction
        self._initialized = False

    def update(self, preds: torch.Tensor, target: torch.Tensor) -> None:
        # Transpose if dim=1 to ensure consistent handling
        if self.dim == 1:
            preds = preds.T
            target = target.T

        # Initialize states the first time update is called
        if not self._initialized:
            # Always use the second dimension after transposing
            self.num_outputs = preds.shape[1]
            state_names = ["mean_x", "mean_y", "var_x", "var_y", "corr_xy", "n_total"]
            for state_name in state_names:
                self.add_state(
                    state_name,
                    default=torch.zeros(self.num_outputs).to(self.device),
                    dist_reduce_fx=None,
                )
            self._initialized = True

        # Update the states
        super().update(preds, target)

    def compute(self):
        # Get the original pearson correlation coefficient
        corrcoef = super().compute()

        # Apply the specified reduction
        if self.reduction == "mean":
            return torch.mean(corrcoef)
        elif self.reduction == "sum":
            return torch.sum(corrcoef)
        else:  # No reduction
            return corrcoef

    def reset(self) -> None:
        self._initialized = False
        super().reset()


import Levenshtein

vocab = {
    "s": 0,
    "o": 1,
    "t": 2,
    "e": 3,
    "n": 4,
    "c": 5,
    "i": 6,
    "a": 7,
    " ": 8,
    "d": 9,
    "l": 10,
    "r": 11,
    "b": 12,
    "@": 13,
    "z": 14,
    "v": 15,
    "f": 16,
    "m": 17,
    "u": 18,
    "h": 19,
    "p": 20,
    "g": 21,
    "q": 22,
    "w": 23,
    "x": 24,
    "y": 25,
    "j": 26,
    "ý": 27,
    "\x14": 28,
    "k": 29,
    "ü": 30,
    "û": 31,
    "£": 32,
    "¤": 33,
    "9": 34,
    "-": 35,
    "¿": 36,
    "\u0060": 37,
    "_": 38,
}

class CharacterErrorRateMetricBaseline(torchmetrics.Metric):
    def __init__(self, dist_sync_on_step=False):
        super().__init__(dist_sync_on_step=dist_sync_on_step)

        self.index_to_char = {v: k for k, v in vocab.items()}
        self.add_state("total_distance", default=torch.tensor(0.0), dist_reduce_fx="sum")
        self.add_state("total_length", default=torch.tensor(0), dist_reduce_fx="sum")

    def update(self, y_pred, y_true):
        _, max_indices = torch.max(y_pred, 1)
        decoded_sequence = [self.index_to_char.get(idx.item(), "") for idx in max_indices]
        sentence = [self.index_to_char.get(idx.item(), "") for idx in y_true]
        distance = Levenshtein.distance("".join(decoded_sequence), "".join(sentence))
        length = max(len(sentence), 1)
        normalized_distance = distance / length
        self.total_distance += normalized_distance
        self.total_length += 1

    def compute(self):
        if self.total_length == 0:
            return torch.tensor(0.0)
        return self.total_distance / self.total_length


class Rank(torchmetrics.Metric):
    """Rank of predictions based on a retrieval set, using cosine similarity.

    Parameters
    ----------
    reduction :
        How to reduce the example-wise ranks.
    max_samples :
        Maximum expected number of instances in the retrieval set. Used to build the internal
        histogram of seen ranks.
    """

    is_differentiable: bool = False
    higher_is_better: bool = False
    full_state_update: bool = True

    def __init__(
        self,
        reduction: tp.Literal["mean", "median", "std"] = "median",
        relative: bool = False,
    ):
        super().__init__()

        self.reduction = reduction
        self.relative = relative
        self.add_state(
            "ranks",
            default=torch.Tensor([]),
            dist_reduce_fx="cat",
        )
        self.rank_count: torch.Tensor  # For mypy

    @classmethod
    def _compute_sim(cls, x, y, norm_kind="y", eps=1e-15):
        if norm_kind is None:
            eq, inv_norms = "b", torch.ones(x.shape[0])
        elif norm_kind == "x":
            eq, inv_norms = "b", 1 / (eps + x.norm(dim=(1), p=2))
        elif norm_kind == "y":
            eq, inv_norms = "o", 1 / (eps + y.norm(dim=(1), p=2))
        elif norm_kind == "xy":
            eq = "bo"
            inv_norms = 1 / (
                eps + torch.outer(x.norm(dim=(1), p=2), y.norm(dim=(1), p=2))
            )
        else:
            raise ValueError(f"norm must be None, x, y or xy, got {norm_kind}.")

        # Normalize inside einsum to avoid creating a copy of candidates which can be pretty big
        return torch.einsum(f"bc,oc,{eq}->bo", x, y, inv_norms)

    @staticmethod
    def _compute_ranks_from_scores(
        scores: torch.Tensor,
        true_scores: torch.Tensor,
        retrieval_size: int | None,
    ) -> torch.Tensor:
        """Average ranks obtained with stricly greater-than and greater-than-or-equals operations
        to account for repeated scores.

        E.g., the zero-based rank of prediction "1" in [0, 1, 1, 1, 2] will be 2 (instead of 1
        or 3).
        """
        ranks_gt = (scores > true_scores).nansum(dim=1)
        ranks_ge = (scores >= true_scores).nansum(dim=1) - 1
        ranks = (ranks_gt + ranks_ge) / 2
        ranks[ranks < 0] = len(scores) // 2  # FIXME
        if retrieval_size is not None:
            ranks /= retrieval_size
        return ranks

    def _compute_ranks(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
        x_labels: None | list[str] = None,
        y_labels: None | list[str] = None,
    ) -> torch.Tensor:
        scores = self._compute_sim(x, y)

        if x_labels is not None and y_labels is not None:
            # Use explicit mapping to match predictions and targets
            true_inds = torch.tensor(
                [y_labels.index(x) for x in x_labels],
                dtype=torch.long,
                device=scores.device,
            )[:, None]
            true_scores = torch.take_along_dim(scores, true_inds, dim=1)
        else:
            # Assume 1:1 mapping of predictions and targets
            assert x_labels is None and y_labels is None
            assert x.shape[0] == y.shape[0]
            true_scores = torch.diag(scores)[:, None]

        return self._compute_ranks_from_scores(
            scores, true_scores, len(y) if self.relative else None
        )

    @torch.inference_mode()
    def update(
        self,
        x: torch.Tensor,
        y: torch.Tensor,
        x_labels: None | list[str] = None,
        y_labels: None | list[str] = None,
    ) -> None:
        """Update internal list of ranks.

        Parameters
        ----------
        x :
            Tensor of predictions, of shape (N, F).
        y :
            Tensor of retrieval set examples, of shape (M, F).
        x_labels, y_labels :
            If provided, used to match predictions and ground truths that don't have the same
            number of examples. Should have length of N and M, respectively
        """
        ranks = self._compute_ranks(x, y, x_labels, y_labels)
        self.ranks = torch.cat([self.ranks, ranks])  # type: ignore

    def compute(self) -> torch.Tensor:
        agg_func: tp.Callable
        if self.reduction == "mean":
            agg_func = torch.mean
        elif self.reduction == "median":
            agg_func = torch.median
        elif self.reduction == "std":
            agg_func = torch.std
        else:
            raise ValueError(
                f'Unknown aggregation {self.reduction} for computing metric. Available aggregations are: "mean", "median" or "std".'
            )
        return agg_func(self.ranks)

    def _compute_macro_average(
        self, ranks: torch.Tensor, labels: list[str]
    ) -> tp.Dict[str, float]:
        """
        Compute the average rank for each class.
        """
        assert len(ranks) == len(labels)
        groups = defaultdict(list)
        agg_func = np.mean if self.reduction == "mean" else np.median
        for i, label in enumerate(labels):
            groups[label].append(ranks[i])
        return {label: agg_func(ranks) for label, ranks in groups.items()}  # type: ignore

    @classmethod
    def _compute_topk_scores(
        cls,
        x: torch.Tensor,
        y: torch.Tensor,
        y_labels: list[str],
        k: int = 5,
    ) -> tp.Tuple[list[list[str]], list[list[float]]]:
        """
        Compute the top-k predictions and scores for each example in x.
        """
        scores = cls._compute_sim(x, y)
        topk_inds = torch.argsort(scores, dim=1, descending=True)[:, :k]
        topk_labels = [[y_labels[ind] for ind in inds] for inds in topk_inds]
        scores = [
            [scores[i, ind].item() for ind in inds] for i, inds in enumerate(topk_inds)
        ]
        return topk_labels, scores


class TopkAcc(Rank):
    """Top-k accuracy.

    Parameters
    ----------
    topk :
        K in top-k, i.e. minimal rank to classify a prediction as a success.
    """

    is_differentiable: bool = False
    higher_is_better: bool = True
    full_state_update: bool = True

    def __init__(self, topk: int = 5):
        super().__init__(relative=False)
        self.topk = topk

    def _compute_macro_average(
        self, ranks: torch.Tensor, labels: list[str]
    ) -> dict[str, float]:
        """
        Compute the top-k accuracy for each class.
        """
        groups = defaultdict(list)
        for i, label in enumerate(labels):
            groups[label].append(ranks[i])
        return {
            label: float(np.mean([r < self.topk for r in ranks]))
            for label, ranks in groups.items()
        }  # type: ignore

    def compute(self) -> torch.Tensor:
        ranks = self.ranks
        return (ranks < self.topk).float().mean()


class TopkAccFromScores(TopkAcc):
    """Top-k accuracy computed from already available similarity scores.

    Parameters
    ----------
    topk :
        K in top-k, i.e. minimal rank to classify a prediction as a success.
    true_labels :
        Defines where to look for the scores of true pairs. If "first", use the scores in the first
        column of the scores matrix; if "diagonal", use the scores on the diagonal.
    """

    def __init__(
        self, topk: int = 5, true_labels: tp.Literal["first", "diagonal"] = "first"
    ):
        super().__init__(topk)
        self.true_labels = true_labels

    def _compute_ranks(self, scores: torch.Tensor) -> torch.Tensor:  # type: ignore[override]
        if self.true_labels == "first":
            true_scores = scores[:, [0]]
        elif self.true_labels == "diagonal":
            true_scores = torch.diag(scores)
        else:
            raise RuntimeError

        return self._compute_ranks_from_scores(scores, true_scores, None)

    @torch.inference_mode()
    def update(self, scores: torch.Tensor) -> None:  # type: ignore[override]
        """Update internal list of ranks."""
        ranks = self._compute_ranks(scores)
        self.ranks = torch.cat([self.ranks, ranks])  # type: ignore
