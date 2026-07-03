# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing as tp
from pathlib import Path
from warnings import warn

import numpy as np
import pandas as pd
import torch
from torch import nn
from tqdm import tqdm

import neuralset as ns
from neuralset.pipelines import TimeDecoding

logger = logging.getLogger(__name__)


class TorchTimeDecoding(TimeDecoding):
    """Stepwise decoding/encoding pipeline where neuro data is first transformed by a torch module.

    Parameters
    ----------
    checkpoint_path:
        Path to the model checkpoint file. The model should expect an input of shape (B, C, T) and
        output (multiple - see `output_index`) tensors of shape (B, F, T).
    ch_pos_kwargs:
        If provided, instantiate channel position feature with these keyword arguments and feed
        channel positions to the torch module.
    output_picker:
        If provided, the model output will be indexed at this position or extracted in the case of
        a dict (e.g. useful for multi-output models).
    reduce_time_dim:
        If provided, the time dimension of the model output will be reduced,
        i.e. (B, F, T) -> (B, F', 1). Useful if a single prediction should be obtained by segment.
    batch_size:
        Batch size to use for forward pass through the model.
    num_workers:
        Number of workers in dataloader.
    device:
        Device to use for model.

    NOTE: Since the object UID is not affected by the content of the checkpoint file, be aware that
    cached results will be reloaded  if infra["folder"] is not None.
    """

    name: tp.Literal["TorchTimeDecoding"] = "TorchTimeDecoding"  # type: ignore

    checkpoint_path: Path | str  # path to model checkpoint
    ch_pos_kwargs: dict[str, tp.Any] | None = None
    output_picker: int | str | None = None
    reduce_time_dim: tp.Literal["mean", "concat"] | int | None = None
    batch_size: int = 256
    num_workers: int = 10
    device: tp.Literal["cpu", "cuda"] = "cpu"
    infra: ns.infra.MapInfra = ns.infra.MapInfra(folder=None, keep_in_ram=False)

    _torch_model: nn.Module | None = None

    def model_post_init(self, __context):
        super().model_post_init(__context)
        if self.infra.folder is not None or self.infra.keep_in_ram:
            warn(
                "Cache UID will not change if model checkpoint changes. "
                "Consider setting infra.folder=None and infra.keep_in_ram=False."
            )

    def prepare(self) -> pd.DataFrame:
        checkpoint_path = self.checkpoint_path
        if not Path(self.checkpoint_path).is_file():
            checkpoint_path = self.infra.uid_folder() / checkpoint_path  # type: ignore
        self._torch_model = torch.load(
            checkpoint_path, weights_only=False, map_location=self.device
        ).eval()
        events = super().prepare()

        if self.ch_pos_kwargs is not None:
            channel_positions = ns.features.ChannelPositions(
                neuro=self.neuro,  # type: ignore
                **self.ch_pos_kwargs,
            )
            channel_positions.prepare(events)
            self._features["channel_positions"] = channel_positions
        return events

    def _get_X_y_group_from_dataset(
        self,
        dataset: ns.SegmentDataset,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        dataloader = dataset.build_dataloader(
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
        )

        assert (
            self._torch_model is not None
        ), "Torch model not initialized, please call decoder.prepare() first."
        X_batches, y_batches, groups_batches = [], [], []
        with torch.inference_mode():
            for batch in tqdm(dataloader, "Feeding batches to torch model"):
                kwargs = {}
                if (ch_pos := batch.data.get("channel_positions", None)) is not None:
                    kwargs["channel_positions"] = ch_pos.to(self.device)

                out = self._torch_model.forward(
                    batch.data["neuro"].to(self.device),
                    **kwargs,
                )
                if self.output_picker is not None:
                    out = out[self.output_picker]

                X_batches.append(out.detach().cpu().numpy())
                y_batches.append(batch.data["target"].detach().cpu().numpy())
                if self.group is not None:
                    groups_batches.append(batch.data["group"].detach().cpu().numpy())

        X = np.concatenate(X_batches, axis=0)
        if X.ndim != 3:
            raise ValueError(f"X must have dimensions (B, F, T), but got {X.shape}.")
        if self.reduce_time_dim == "mean":
            X = X.mean(axis=2, keepdims=True)
        elif self.reduce_time_dim == "concat":
            X = X.reshape((X.shape[0], -1, 1))
        elif isinstance(self.reduce_time_dim, int):
            X = np.concatenate(
                [
                    x.mean(axis=2, keepdims=True)
                    for x in np.array_split(
                        X, min(self.reduce_time_dim, X.shape[2]), axis=2
                    )
                ],
                axis=1,
            )

        y = np.concatenate(y_batches, axis=0)
        groups = None if self.group is None else np.concatenate(groups_batches, axis=0)

        return X, y, groups

    # NOTE: Do not use infra as we are not caching results and don't want to spawn more jobs
    # pylint: disable=useless-parent-delegation
    def _run_on_subject(self, subjects: list[str]) -> tp.Iterator[np.ndarray]:
        return super()._run_on_subject(subjects)
