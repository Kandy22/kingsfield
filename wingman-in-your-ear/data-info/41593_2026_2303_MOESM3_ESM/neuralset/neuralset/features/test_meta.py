# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
from pathlib import Path

import pytest
import torch

import neuralset as ns


@pytest.mark.parametrize("time_aggregation", ["average", "first"])
def test_time_aggregated_feature(
    tmp_path: Path, time_aggregation: tp.Literal["average", "first"]
) -> None:
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query="timeline_index<2"
    ).build()

    meg = ns.features.Meg(frequency=100.0)
    aggregated_meg = ns.features.TimeAggregatedFeature(
        feature=meg, time_aggregation=time_aggregation
    )
    meg.prepare(events)

    features = {"meg": meg, "agg": aggregated_meg}
    segments = ns.segments.list_segments(
        events,
        idx=events.type == "Image",
        start=0.0,
        duration=3.0,
    )
    dataset = ns.SegmentDataset(
        features,
        segments,
    )
    out = dataset.as_one_batch().data

    assert out["meg"].ndim == 3
    assert out["agg"].ndim == 2
    assert out["agg"].shape[0] == out["meg"].shape[0]
    assert out["agg"].shape[1] == out["meg"].shape[1]
    if time_aggregation == "average":
        assert torch.allclose(out["agg"], out["meg"].mean(-1))
    elif time_aggregation == "first":
        assert torch.allclose(out["agg"], out["meg"][..., 0])


@pytest.mark.parametrize("agg_method", ["average", "sum", "cat", "stack"])
def test_aggregated_feature(
    tmp_path: Path, agg_method: tp.Literal["average", "sum", "cat", "stack"]
) -> None:
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query="timeline_index<2"
    ).build()

    meg = ns.features.Meg(frequency=100.0, aggregation="single")
    meg.prepare(events)

    agg_feature = ns.features.AggregatedFeature(
        features=[meg, meg], feature_aggregation=agg_method
    )
    features = {"meg": meg, "agg": agg_feature}
    segments = ns.segments.list_segments(
        events,
        idx=events.type == "Image",
        start=0.0,
        duration=3.0,
    )
    dataset = ns.SegmentDataset(
        features,
        segments,
    )
    out = dataset.as_one_batch().data

    if agg_method in ["average", "sum", "cat"]:
        assert out["agg"].ndim == 3
    elif agg_method == "stack":
        assert out["agg"].ndim == 4
    assert out["agg"].shape[0] == out["meg"].shape[0]
    assert out["agg"].shape[-1] == out["meg"].shape[-1]

    if agg_method == "cat":
        assert out["agg"].shape[1] == 2 * out["meg"].shape[1]
    elif agg_method == "average":
        assert out["agg"].shape[1] == out["meg"].shape[1]
        assert torch.allclose(out["agg"], out["meg"])
    elif agg_method == "sum":
        assert out["agg"].shape[1] == out["meg"].shape[1]
        assert torch.allclose(out["agg"], out["meg"] * 2)
    elif agg_method == "stack":
        assert out["agg"].shape[1] == 2
        assert out["agg"].shape[2] == out["meg"].shape[1]
        assert out["agg"].shape[3] == out["meg"].shape[2]
        assert torch.allclose(out["agg"][:, 0], out["meg"])

    f1 = ns.features.WordFrequency(event_types="Word", aggregation="first")
    f2 = ns.features.WordFrequency(event_types="Word", aggregation="last")
    f1.prepare(events)
    f2.prepare(events)
    agg = ns.features.AggregatedFeature(
        features=[f1, f2], feature_aggregation=agg_method, aggregation="trigger"
    )
    features = {"agg": agg}
    segments = ns.segments.list_segments(
        events,
        idx=events.type == "Word",
        start=0.0,
        duration=3.0,
    )
    dataset = ns.SegmentDataset(
        features,
        segments,
    )
    out = dataset.as_one_batch().data

    batch_size = len(segments)
    if agg_method in ["average", "sum"]:
        assert out["agg"].shape == (batch_size, 1)
    elif agg_method == "cat":
        assert out["agg"].shape == (batch_size, 2)
    else:
        assert out["agg"].shape == (batch_size, 2, 1)
