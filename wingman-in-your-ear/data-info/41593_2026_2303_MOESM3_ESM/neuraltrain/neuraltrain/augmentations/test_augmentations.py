# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp

import pytest
import torch
from torch.utils.data import DataLoader

import neuralset as ns  # type: ignore
from neuralset.test_dataloader import _make_segments  # type: ignore

from .augmentations import (
    AugmentedSegmentDataset,
    BandstopFilterFFT,
    TrivialBrainAugment,
    TrivialBrainAugmentConfig,
)


@pytest.mark.parametrize("sfreq", [100, 250])
@pytest.mark.parametrize("bandwidth", [2, 4])
def test_bandstop_filter_fft(sfreq, bandwidth):
    transform = BandstopFilterFFT(sfreq=sfreq, bandwidth=bandwidth)
    x = torch.randn(10, 2, 512)
    z = transform(x)
    # Only check shape for now
    assert z.shape == x.shape


@pytest.mark.parametrize("sfreq", [100, 250])
def test_trivial_brain_augment(sfreq):
    transform = TrivialBrainAugment(TrivialBrainAugmentConfig(sfreq=sfreq))
    x = torch.randn(10, 2, 512)
    z = transform(x)
    # Only check shape for now
    assert z.shape == x.shape


def test_augmented_segment_dataset() -> None:
    # A study is just a dataframe of events
    segments = _make_segments()
    pulse = ns.features.Pulse(frequency=100.0)
    feats: tp.Any = {"transformed": pulse, "untransformed": pulse}
    ds = AugmentedSegmentDataset(
        feats,
        segments,
        transforms={"transformed": lambda a: a * 2},
    )
    dataloader: DataLoader = DataLoader(ds, collate_fn=ds.collate_fn, batch_size=2)
    batch = next(iter(dataloader))
    assert batch.data["transformed"].shape == (2, 1, 100)
    assert batch.data["untransformed"].shape == (2, 1, 100)
    assert torch.all(batch.data["transformed"] == batch.data["untransformed"][:, :1] * 2)
