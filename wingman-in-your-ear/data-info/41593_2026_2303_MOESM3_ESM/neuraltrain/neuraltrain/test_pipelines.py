# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
from pathlib import Path

import pytest
import torch
from torch import nn

import neuralset as ns

from .pipelines import TorchTimeDecoding


class DummyModel(nn.Module):
    def __init__(self, return_type: tp.Literal["tensor", "tuple", "dict"]) -> None:
        super().__init__()
        self.linear = nn.LazyLinear(5)
        self.return_type = return_type

    def forward(
        self, x: torch.Tensor, channel_positions: torch.Tensor | None = None
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor] | dict[str, torch.Tensor]:
        out = self.linear(x)
        if channel_positions is not None:
            assert x.shape[:2] == channel_positions.shape[:2]

        if self.return_type == "tensor":
            return out
        elif self.return_type == "tuple":
            return out, out + 1
        elif self.return_type == "dict":
            return {"y1": out, "y2": out + 1}


@pytest.fixture
def model_checkpoint_path(tmp_path: Path) -> Path:
    model = DummyModel(return_type="tuple")
    checkpoint_path = tmp_path / "best.ckpt"
    torch.save(model, checkpoint_path)
    return checkpoint_path


@pytest.mark.parametrize("reduce_time_dim", [None, "concat", "mean", 3])
def test_torch_time_decoding(model_checkpoint_path, reduce_time_dim) -> None:
    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    decoder = TorchTimeDecoding(
        study=study,
        model_name="RidgeClassifierCV",
        task="decode",
        checkpoint_path=model_checkpoint_path,
        output_picker=0,
        reduce_time_dim=reduce_time_dim,
        event_type="Stimulus",
        start=0.1,
        duration=1,
        neuro=ns.features.Meg(),
        target=ns.features.Stimulus(aggregation="trigger"),
    )

    scores = decoder.run()
    if reduce_time_dim is None:
        assert scores.shape == (1, 5, 1)
    else:
        assert scores.shape == (1, 1, 1)


@pytest.mark.parametrize(
    "return_type,output_picker",
    [["tensor", None], ["tuple", 1], ["dict", "y1"]],
)
def test_torch_time_decoding_output_picker(tmp_path, return_type, output_picker) -> None:
    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)

    model = DummyModel(return_type=return_type)
    checkpoint_path = tmp_path / "best.ckpt"
    torch.save(model, checkpoint_path)

    decoder = TorchTimeDecoding(
        study=study,
        model_name="RidgeClassifierCV",
        task="decode",
        checkpoint_path=checkpoint_path,
        output_picker=output_picker,
        reduce_time_dim=None,
        event_type="Stimulus",
        start=0.1,
        duration=1,
        neuro=ns.features.Meg(),
        target=ns.features.Stimulus(aggregation="trigger"),
    )
    decoder.run()


def test_torch_time_decoding_ch_pos(model_checkpoint_path, tmp_path: Path) -> None:
    ch_pos_kwargs = {"layout_or_montage_name": "EEG1005", "include_ref_eeg": True}

    study = ns.data.StudyLoader(
        name="TestEeg2024", path=tmp_path, infra={"cluster": None}  # type: ignore
    )
    decoder = TorchTimeDecoding(
        study=study,
        model_name="RidgeCV",
        ch_pos_kwargs=ch_pos_kwargs,
        task="decode",
        checkpoint_path=model_checkpoint_path,
        output_picker=1,
        event_type="Word",
        start=0.0,
        duration=0.2,
        neuro=ns.features.Eeg(),
        target=ns.features.WordLength(),
    )

    scores = decoder.run()
    assert scores.shape == (3, 5, 1)
