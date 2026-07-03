# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
from pathlib import Path

import numpy as np
import pandas as pd
import pydantic
import pytest
import torch
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

import neuralset as ns
from neuralset.base import TimedArray
from neuralset.infra import ConfDict, TaskInfra

from . import base


class ExternFeat(ns.features.Pulse):
    name: tp.Literal["ExternFeat"] = "ExternFeat"  # type: ignore


ns.features.update_config_feature()


class Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    features: tp.Sequence[ns.features.FeatureConfig] = ()


def test_features_model() -> None:
    model = Model(features=[{"name": "Pulse"}, {"name": "Meg", "frequency": 12}, {"name": "ExternFeat"}])  # type: ignore
    cfg = ConfDict.from_model(model, uid=True, exclude_defaults=True)
    assert (
        cfg.to_yaml()
        == """features:
- name: Pulse
- frequency: 12.0
  name: Meg
- name: ExternFeat
"""
    )


def test_dynamic_feature() -> None:
    # word pulse
    feature = base.Pulse(frequency=1.0, aggregation="sum", event_types="Word")

    event = dict(
        type="Word",
        text="test",
        start=0.0,
        duration=2.0,
        language="english",
        timeline="foo",
    )

    # single event and slicing
    out = feature(event, start=0.0, duration=4.0)
    assert np.array_equal(out, [[1, 1, 0, 0]])
    # segment does not overlap with event
    out = feature(event, start=-4.0, duration=4.0)
    assert np.array_equal(out, [[0, 0, 0, 0]])
    # overwrite event duration (legacy BaseStatic.duration = 1.0)
    event2 = dict(event)
    event2["duration"] = 1.0
    out = feature(event2, start=0.0, duration=4.0)
    assert np.array_equal(out, [[1, 0, 0, 0]])
    # event start after segment
    event["start"] = 2.0
    out = feature(event, start=0.0, duration=4.0)
    assert np.array_equal(out, [[0, 0, 1, 1]])
    # event start before segment and ends when segment starts
    event["start"] = -2.0
    out = feature(event, start=0.0, duration=4.0)
    assert np.array_equal(out, [[0, 0, 0, 0]])
    # event start before segment and ends within segment
    event["duration"] = 4.0
    out = feature(event, start=0.0, duration=4.0)
    assert np.array_equal(out, [[1, 1, 0, 0]])
    # segment starts before 0
    out = feature(event, start=-1.0, duration=4.0)
    assert np.array_equal(out, [[1, 1, 1, 0]])

    # list of events
    segment = dict(events=pd.DataFrame([event]), start=0, duration=4.0)
    data = feature(**segment)  # type: ignore
    assert data.max() == 1 and data.min() == 0
    assert np.array_equal(data.shape, (1, 4))

    # two sequential events
    kwargs = dict(type="Word", text="test", language="english", timeline="foo")
    events = pd.DataFrame(
        [
            dict(start=0.0, duration=1.0, **kwargs),
            dict(start=2.0, duration=1.0, **kwargs),
        ]
    )
    out = feature(events, start=0.0, duration=4)
    assert np.array_equal(out, [[1, 0, 1, 0]])

    # check two simultaneous events
    events = pd.DataFrame(
        [
            dict(start=1.0, duration=2.0, **kwargs),
            dict(start=2.0, duration=2.0, **kwargs),
        ]
    )
    out = feature(events, start=0.0, duration=4.0)
    assert np.array_equal(out, [[0, 1, 2, 1]])

    # test static feature
    feature = base.Pulse(aggregation="sum", event_types="Word")
    out = feature(events, start=0.0, duration=4.0)
    assert np.array_equal(out, [2.0])
    # TODO wordpulse + phonemepulse?


def test_stimulus() -> None:
    code = 1
    feature = base.Stimulus()
    event = dict(
        type="Stimulus",
        code=code,
        description="test",
        start=0.0,
        duration=2.0,
        timeline="foo",
    )
    out = feature(event, start=0.0, duration=4.0)
    assert out == torch.tensor(code)


def test_button_class() -> None:
    feature = ns.features.ButtonClass()

    event = dict(
        type="Button",
        button="a",
        start=0.0,
        duration=2.0,
        timeline="foo",
    )

    # Test with a single event
    out = feature(event, start=0.0, duration=4.0)
    assert out == torch.tensor(7)  # 'a' is mapped to 7

    # Test with a DataFrame of events
    events = pd.DataFrame(
        [
            dict(type="Button", button="a", start=0.0, duration=2.0, timeline="foo"),
            dict(type="Button", button="z", start=2.0, duration=2.0, timeline="foo"),
        ]
    )

    out = torch.tensor([feature.get_static(e) for e in events.itertuples()])
    assert torch.equal(out, torch.tensor([7, 14]))


class Time(base.BaseFeature):
    """Simple dynamic feature for testing fill_slice"""

    name: tp.Literal["Time"] = "Time"
    event_types: str | tp.Tuple[str, ...] = "BaseDataEvent"
    frequency: float = 50.0  # default output frequency

    def _get_timed_arrays(
        self, events: list[ns.events.Event], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        for event in events:
            length = max(1, base.Frequency(self.frequency).to_ind(event.duration))
            data = np.linspace(event.start, event.start + event.duration, length)[None, :]
            yield TimedArray(
                data=data,
                start=event.start,
                duration=event.duration,
                frequency=self.frequency,
            )


@pytest.mark.parametrize(
    "start,duration,expected",
    [
        (0.5, 0.6, [0.6, 0.8, 1, 0]),  # side 1
        (-0.5, 1, [0, 0, 0, 0, 0.2, 0.4]),  # side 2
        (0.2, 0.6, [0.2, 0.4, 0.6, 0.8]),  # inside
        (-0.2, 1.4, [0, 0, 0.2, 0.4, 0.6, 0.8, 1, 0]),  # around
        (0.5, 0.1, [0.6]),  # small (half freq)
        (0.5, 0.01, [0.6]),  # smaller  (we may want to decide there is no sample?)
        (2, 1, [0, 0, 0, 0, 0, 0]),  # no overlap after
        (-2, 1, [0, 0, 0, 0, 0, 0]),  # no overlap before
    ],
)
def test_fill_slice(start: float, duration: float, expected: tp.List[float]) -> None:
    feat = Time(frequency=6, event_types=("Image", "Text"))
    event = ns.events.Image(start=0, duration=1, timeline="stuff", filepath=__file__)
    out = feat(event, start=start, duration=duration)[0]
    np.testing.assert_array_almost_equal(out, expected)


def test_fill_small_event() -> None:
    feat = Time(frequency=6)
    event = ns.events.Image(start=0.5, duration=0.01, timeline="stuff", filepath=__file__)
    out = feat(event, start=0, duration=1)[0]
    np.testing.assert_array_almost_equal(out, [0, 0, 0, 0.5, 0, 0])


@pytest.mark.parametrize(
    "aggreg,expected",
    [
        ("first", [0, 0.5, 1.0]),
        ("trigger", [0, 0, 0.7]),
        ("sum", [0, 0.5, 1.0]),
        ("average", [0, 0.5, 1.0]),
    ],
)
def test_trigger(
    aggreg: tp.Literal["first", "trigger"], expected: tp.List[float]
) -> None:
    feat = Time(frequency=3, aggregation=aggreg)
    event = ns.events.Image(start=0, duration=1, timeline="stuff", filepath=__file__)
    trigger = ns.events.Image(
        start=0.7, duration=1, timeline="stuff", filepath=__file__
    ).to_dict()
    out = feat(event, start=0, duration=1, trigger=trigger)[0]
    np.testing.assert_array_almost_equal(out, expected)
    # exceptions
    if aggreg == "trigger":
        with pytest.raises(ValueError):
            feat(event, start=0, duration=1, trigger=None)


def test_fill_slice_load_testing() -> None:
    seed = np.random.randint(2**32 - 1)
    for k in range(1000):
        print(f"Seeding with {seed + k} for reproducibility")
        rng = np.random.default_rng(seed + k)
        freq = rng.uniform(0, 50)
        if freq > 1 and rng.integers(2):
            freq = int(freq)
        feat = Time(frequency=freq)
        event = ns.events.Image(
            start=rng.uniform(0, 1),
            duration=rng.uniform(0, 1),
            timeline="stuff",
            filepath=__file__,
        )
        start = event.start + rng.uniform(-0.1, 0.1)
        end = event.start + event.duration + rng.uniform(-0.1, 0.1)
        duration = end - start
        if duration < 0:
            duration = rng.uniform(0.1, 0.2)
        feat(event, start=start, duration=duration)


def test_meg_border_cases(tmp_path: Path) -> None:
    # neuro has its own fill slice to deal with mne, so
    # we need a similar check
    query = "timeline_index < 1"
    loader = ns.data.StudyLoader(name="TestMeg2023", path=tmp_path / "data", query=query)
    events = loader.build()
    event = ns.events.Meg.from_dict(events.query('type=="Meg"').iloc[0])
    seed = np.random.randint(2**32 - 1001)
    for k in range(20):
        print(f"Seeding with {seed + k} for reproducibility")
        rng = np.random.default_rng(seed + k)
        feature = ns.features.Meg(frequency=rng.uniform(10, 50))
        start = event.start + rng.uniform(-1, 2) * event.duration
        duration = event.duration * rng.uniform(0, 1)
        out = feature(event, start=start, duration=duration)
        time_inds = max(1, base.Frequency(feature.frequency).to_ind(duration))
        assert out.shape[1] == time_inds


class Xp(pydantic.BaseModel):
    param1: int = 12
    feature: ns.features.FeatureConfig = ns.features.Pulse()
    infra: TaskInfra = TaskInfra()

    @infra.apply
    def run(self) -> int:
        return self.param1


def test_cfg_feature_uid(tmp_path: Path) -> None:
    xp = Xp(feature={"name": "HuggingFaceImage", "infra": {"folder": tmp_path}})  # type: ignore
    cfg = xp.infra.config(uid=True, exclude_defaults=True)
    assert cfg["feature.name"] == "HuggingFaceImage"


@pytest.mark.parametrize(
    "shape,agg,out",
    [
        ((12, 13, 14, 15), "mean", (12, 14, 15)),
        ((12, 13, 14, 15), "max", (12, 14, 15)),
        ((12, 13, 14, 15), "sum", (12, 14, 15)),
        ((12, 13, 14, 15), "first", (12, 14, 15)),
        ((13, 14, 15), "last", (13, 15)),
        ((13, 14, 15), None, (13, 14, 15)),
    ],
)
def test_hf_aggregate_tokens(
    tmp_path: Path,
    shape: tuple[int, ...],
    agg: str | None,
    out: tuple[int, ...],
) -> None:
    xp = Xp(feature={"name": "HuggingFaceImage", "token_aggregation": agg, "infra": {"folder": tmp_path}})  # type: ignore
    data_n = np.random.rand(*shape)
    data_t = torch.from_numpy(data_n)
    agged_t = xp.feature._aggregate_tokens(data_t)  # type: ignore
    agged_n = xp.feature._aggregate_tokens(data_n)  # type: ignore
    assert agged_t.shape == out
    np.testing.assert_array_almost_equal(agged_t.numpy(), agged_n)


def test_label_encoder(tmp_path: Path) -> None:
    query = "timeline_index < 2"
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query=query
    ).build()

    meg_feature = base.LabelEncoder(
        event_types="Meg",
        event_field="filepath",
        return_one_hot=False,
    )
    img_feature = base.LabelEncoder(
        event_types="Image",
        event_field="filepath",
        return_one_hot=False,
    )
    meg_feature.prepare(events)
    img_feature.prepare(events)

    features = {"Meg": meg_feature, "Image": img_feature}
    segments = ns.segments.list_segments(
        events,
        idx=events.type == "Image",
        start=0.0,
        duration=1.0,
    )
    dataset = ns.SegmentDataset(features=features, segments=segments)
    out_inds = dataset.as_one_batch().data

    assert (out_inds["Meg"][:, 0] == torch.tensor([0, 0, 0, 0, 1, 1, 1, 1])).all()
    assert (out_inds["Image"][:, 0] == torch.tensor([2, 3, 1, 0, 2, 3, 1, 0])).all()


def test_label_encoder_missing(tmp_path: Path) -> None:
    query = "timeline_index < 1"
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query=query
    ).build()

    img_feature = base.LabelEncoder(
        event_types="Image",
        event_field="filepath",
        return_one_hot=False,
        allow_missing=True,
    )
    img_feature.prepare(events)

    segments = ns.segments.list_segments(
        events,
        idx=events.type == "Image",
        start=0.0,
        duration=1.0,
    )
    segments[0] = ns.segments.Segment(
        start=0, duration=1, ns_events=[], _index=np.array([])
    )

    dataset = ns.SegmentDataset(features={"Image": img_feature}, segments=segments)
    out_inds = dataset.as_one_batch().data
    exp = [0, 3, 1, 0]
    assert (out_inds["Image"][:, 0] == torch.tensor(exp)).all()
    assert out_inds["Image"].dtype == torch.long


@pytest.mark.parametrize("return_one_hot", [False, True])
def test_label_encoder_one_hot(tmp_path: Path, return_one_hot: bool) -> None:
    query = "timeline_index < 1"
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query=query
    ).build()

    event_field = "filepath"
    feature = base.LabelEncoder(
        event_types="Image",
        event_field=event_field,
        return_one_hot=return_one_hot,
    )
    feature.prepare(events)
    img_events = events[events.type == "Image"]

    inds = []
    for _, ev in img_events.iterrows():
        event = ns.events.Event.from_dict(ev.to_dict())
        inds.append(feature(event, start=0, duration=1))

    out_inds = torch.stack(inds, dim=0)
    assert len(out_inds) == img_events.shape[0]

    gt_event_field = img_events[event_field].to_numpy().reshape(-1, 1)
    if return_one_hot:
        gt_inds = OneHotEncoder(dtype=int, sparse_output=False).fit_transform(
            gt_event_field
        )
    else:
        gt_inds = OrdinalEncoder(dtype=int).fit_transform(gt_event_field)[:, 0]
    assert (out_inds.squeeze().numpy() == gt_inds).all()


def test_huggingface_model_exists():
    base.HuggingFaceMixin(model_name="gpt2")
    with pytest.raises(ValueError):
        base.HuggingFaceMixin(model_name="not_a_model")


def test_label_encoder_dynamic(tmp_path: Path) -> None:
    query = "timeline_index < 1"
    events = ns.data.StudyLoader(
        name="TestMeg2023", path=tmp_path / "data", query=query
    ).build()

    event_field = "filepath"

    feature = base.LabelEncoder(
        frequency=10,
        aggregation="trigger",
        event_types="Image",
        event_field=event_field,
        return_one_hot=False,
    )

    feature.prepare(events)
    time_segments = ns.segments.list_segments(
        events, idx=events.type == "Image", start=0, duration=1
    )

    dataset = ns.SegmentDataset({"label": feature}, time_segments)
    assert dataset[0].data["label"].ndim == 3
    assert dataset[0].data["label"].shape[-1] == 10
    assert (dataset[0].data["label"] != 0).sum() == 7


def test_label_encoder_predefined_mapping():
    mapping = {"a": 0, "b": 1, "c": 4}
    feature = base.LabelEncoder(
        event_types="Button",
        event_field="text",
        return_one_hot=False,
        predefined_mapping=mapping,
    )

    events = pd.DataFrame(
        [
            {"type": "Button", "text": "a", "start": 0, "timeline": ""},
            {"type": "Button", "text": "b", "start": 0, "timeline": ""},
            {"type": "Button", "text": "c", "start": 0, "timeline": ""},
            {"type": "Button", "text": "c", "start": 0, "timeline": ""},
        ]
    )

    feature.prepare(events)
    out = [
        feature(ns.events.Event.from_dict(e), 0, 1).item() for _, e in events.iterrows()
    ]
    assert out == [0, 1, 4, 4]

    events_bad = pd.DataFrame(
        [
            {"type": "Button", "text": "a", "start": 0, "timeline": ""},
            {"type": "Button", "text": "d", "start": 0, "timeline": ""},  # Not in mapping
        ]
    )

    with pytest.raises(
        AssertionError,
        match="Some labels in the data are missing from the predefined_mapping",
    ):
        feature.prepare(events_bad)


def test_event_detector():
    from neuralset.base import Frequency as Frequency

    freq = 10
    duration = 0.7
    n_samples = Frequency(freq).to_ind(duration)
    events = pd.DataFrame(
        [
            {
                "type": "Meg",
                "start": 0.0,
                "duration": 0.7,
                "frequency": 10,
                "timeline": "",
            },
            {"type": "Word", "start": 0.1, "duration": 0.3, "timeline": ""},
            {"type": "Word", "start": 0.2, "duration": 0.4, "timeline": ""},
        ]
    )

    # === Dense
    f = base.EventDetector(mode="dense", event_types="Word", frequency=freq)
    f.prepare(events)
    out = f(events, start=0.0, duration=duration).data[0]
    expected = np.zeros(n_samples)
    expected[int(0.1 * freq) : int((0.1 + 0.3) * freq)] = 1
    expected[int(0.2 * freq) : int((0.2 + 0.4) * freq)] = 1
    assert np.allclose(out, expected)

    # === Start
    f = base.EventDetector(mode="start", event_types="Word", frequency=freq)
    f.prepare(events)
    out = f(events, start=0.0, duration=duration).data[0]
    expected = np.zeros(n_samples)
    expected[int(0.1 * freq)] = 1
    expected[int(0.2 * freq)] = 1
    assert np.allclose(out, expected)

    # === Center
    f = base.EventDetector(mode="center", event_types="Word", frequency=freq)
    f.prepare(events)
    out = f(events, start=0.0, duration=duration).data[0]
    expected = np.zeros(n_samples)
    expected[int((0.1 + 0.15) * freq)] = 1
    expected[int((0.2 + 0.2) * freq)] = 1
    assert np.allclose(out, expected)

    # === Duration
    f = base.EventDetector(mode="duration", event_types="Word", frequency=freq)
    f.prepare(events)
    out = f(events, start=0.0, duration=duration).data[0]
    expected = np.zeros(n_samples)
    expected[int((0.1 + 0.15) * freq)] = 0.3 / duration
    expected[int((0.2 + 0.2) * freq)] = 0.4 / duration
    assert np.allclose(out, expected)
