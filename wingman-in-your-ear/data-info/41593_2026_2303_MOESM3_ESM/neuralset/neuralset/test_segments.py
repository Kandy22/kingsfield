# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import pickle
import typing as tp
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import neuralset as ns
import neuralset.segments as seg
from neuralset.segments import list_segments

from . import utils
from .test_splitting import create_wav


def test_segment() -> None:
    ev = ns.events.Word(start=0, timeline="t", duration=1, text="whatever")
    segment = seg.Segment(start=0, duration=1, _index=np.array([12]), ns_events=[ev])
    df = segment.events
    assert tuple(df.index) == (12,)
    assert len(segment.events) == 1
    assert len(segment.ns_events) == 1
    assert set(segment._to_feature()) == {"events", "start", "duration", "trigger"}


@pytest.mark.parametrize("reloaded", (True, False))
@pytest.mark.parametrize("validated", (True, False))
def test_find_intersect(reloaded: bool, validated: bool, tmp_path: Path) -> None:
    #  |-----A----|
    #     |--B--|
    #     |-----C-----|
    # |----D----|
    #                |---E---]

    events = pd.DataFrame(
        {
            "type": ["a", "b", "c", "d", "e"],
            "start": [-0.5, 0.0, 0.0, -1.0, 10.0],
            "duration": [2.0, 1.0, 2.0, 2.0, 2.0],
            "timeline": [1, 1, 1, 1, 1],
        }
    )
    if validated:
        with utils.ignore_all():
            events = seg.validate_events(events)

    sel = events.type == "a"
    starts = events.loc[sel].start.to_numpy()
    durations = events.loc[sel].duration.to_numpy()

    # Test case: find overlaping events
    segments = list(seg.intersection_segments(events, starts, durations))
    expected = "dacb" if validated else "abcd"
    assert "".join(events.loc[segments[0]._index].type) == expected

    # Test case: same with isolated event
    sel = events.type == "e"
    starts = events.loc[sel].start.to_numpy()
    durations = events.loc[sel].duration.to_numpy()

    segments = list(seg.intersection_segments(events, starts, durations))
    assert "".join(events.loc[segments[0]._index].type) == "e"

    assert isinstance(segments[0].start, float)
    assert isinstance(segments[0].duration, float)

    # test ns api
    events = seg.validate_events(
        pd.DataFrame(
            {
                "type": ["Word"] * 6,
                "text": ["a", "b", "c", "d", "e", "f"],
                "start": [-0.5, 0, 0, -1, 10, 0],
                "duration": [2, 1, 2, 2, 2, 3],
                "timeline": [str(k) for k in [1, 1, 1, 1, 1, 2]],
            }
        )
    )
    if reloaded:
        # dump and reload to test for changed column dtypes
        fp = tmp_path / "data.parquet"
        events.to_parquet(fp)
        events = pd.read_parquet(fp, dtype_backend="numpy_nullable")

    # check _iter index dtype:
    actual = seg.find_overlap(events, events.index[0])
    assert "".join(events.loc[actual].text) == "dacb"

    actual = seg.find_overlap(events, events.text == "a")
    assert "".join(events.loc[actual].text) == "dacb"
    # cannot find overlap from a specific time if multiple timeline
    with pytest.raises(AssertionError):
        actual = seg.find_overlap(events, start=0.0, duration=1.0)

    actual = seg.find_overlap(events.query("timeline=='1'"), start=0.0, duration=1.0)
    assert "".join(events.loc[actual].text) == "dacb"

    actual = seg.find_overlap(events, events.text == "f")
    assert "".join(events.loc[actual].text) == "f"

    expected_list = "d", "da", "dacb", "dacb", "e", "f"
    actual_segments = seg.list_segments(events, pd.Series(events.index), duration=0.1)
    for act, exp in zip(actual_segments, expected_list):
        sub = events.loc[act._index]
        assert sub.timeline.nunique() == 1
        assert "".join(sub.text) == exp

    assert isinstance(actual_segments[0]._trigger, dict)

    # test striding window
    dset = seg.list_segments(events, stride=1.5, duration=3.0)
    assert len(dset) == 8


@pytest.mark.parametrize("index_offset", (0, 12))
def test_trigger(index_offset: int) -> None:
    events = seg.validate_events(
        pd.DataFrame(
            [
                dict(type="Word", start=42.0, duration=1, text="table", timeline="blu"),
                dict(type="Phoneme", start=42.0, duration=1, text="t", timeline="blu"),
                dict(type="Phoneme", start=42.0, duration=1, text="t", timeline="blublu"),
            ]
        )
    )
    events.index = events.index + index_offset
    with pytest.raises(ValueError):
        _ = seg.list_segments(events, events.type == "wrong")
    segs = seg.list_segments(events, events.type == "Word")
    assert len(segs) == 1
    assert len(segs[0].ns_events) == 2, "Event list should be precomputed"  # type: ignore
    assert segs[0]._trigger["type"] == "Word"  # type: ignore
    assert isinstance(segs[0]._index, np.ndarray)
    additional = set(segs[0]._index) - set(events.index)
    assert not additional, "Indices should be in the original dataframe"
    string = pickle.dumps(segs[0])
    pickle.loads(string)


def test_list_segments_duration() -> None:
    data = [dict(type="Word", start=0, duration=100, text="text", timeline="blu")]
    events = seg.validate_events(pd.DataFrame(data))
    duration = 3
    segs = seg.list_segments(events, stride=1.234, duration=duration)
    durations = [s.duration for s in segs]
    assert all(d == duration for d in durations), f"Got {durations}"


def test_segment_to_events_with_fake_events(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    data = [
        dict(type="Word", start=0, duration=100, text="text", timeline="blu"),
        dict(type="Blublu", start=0, duration=100, text="text", timeline="blu"),
    ]
    df = pd.DataFrame(data)
    df = seg.validate_events(df)
    assert not caplog.records
    segs = seg.list_segments(df, stride=1.234, duration=3)
    assert caplog.records
    assert "Blublu" in caplog.text
    _ = segs[0].events


@pytest.mark.parametrize("stride", [5.0, 10.0, 20.0])
@pytest.mark.parametrize("start", [-1.0])
@pytest.mark.parametrize("stride_drop_incomplete", [True, False])
def test_list_segments_idx_stride(
    stride: float,
    start: float,
    stride_drop_incomplete: bool,
) -> None:
    data = [
        dict(type="Word", start=0, duration=100, text="text", timeline="blu"),
        dict(type="Word", start=200, duration=100, text="text", timeline="blu"),
        dict(type="Phoneme", start=200, duration=100, text="text", timeline="blublu"),
    ]
    events = seg.validate_events(pd.DataFrame(data))
    duration = 10
    segs = list_segments(
        events=events,
        idx=events.type == "Word",
        start=start,
        duration=duration,
        stride=stride,
        stride_drop_incomplete=stride_drop_incomplete,
    )

    starts = np.array([s.start for s in segs])
    less_than = np.less if stride_drop_incomplete else np.less_equal
    assert (
        ((starts >= 0.0 + start) & less_than(starts, 100.0 + start))
        | ((starts >= 200.0 + start) & less_than(starts, 300.0 + start))
    ).all()

    strides = np.diff(starts)
    assert sum(strides == stride) == len(strides) - 1

    durations = [s.duration for s in segs]
    assert all(d == duration for d in durations), f"Got {durations}"


def test_find_incomplete_segments(tmp_path: Path) -> None:
    sentence = ("This is a sentence for the unit tests").split(" ")
    words = [
        dict(
            type="Word",
            text=sentence[i],
            start=i,
            duration=1.0,
            language="english",
            timeline="foo",
            split="train",
        )
        for i in range(len(sentence))
    ]
    fp = tmp_path / "noise.wav"
    create_wav(fp, fs=44100, duration=10)
    sound = dict(type="Sound", start=3, timeline="foo", filepath=fp)
    events = [sound] + words
    events_df = seg.validate_events(pd.DataFrame(events))

    segments = seg.list_segments(
        events_df,
        events_df.type == "Word",
        start=-0.5,
        duration=1.0,
    )
    indices = seg.find_incomplete_segments(segments, [ns.events.Sound])
    # the three first words are invalid
    assert len(indices) == 3


@patch("matplotlib.pyplot.figure")
def test_plot_timelines(mock: tp.Any) -> None:
    events = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER).build()
    seg.plot_timelines(events)
    mock.assert_called()


def _make_df() -> pd.DataFrame:
    events = [
        ns.events.Word(start=2, duration=3, text="a", timeline="t2"),
        ns.events.Word(start=1, duration=2, text="b", timeline="t2"),
        ns.events.Word(start=0, duration=2, text="c", timeline="t1"),
        ns.events.Word(start=0, duration=3, text="d", timeline="t1"),
    ]
    df = pd.DataFrame([e.to_dict() for e in events])
    df = seg.validate_events(df)
    return df


def test_sorting() -> None:
    df = _make_df()
    assert tuple(df.text) == ("b", "a", "d", "c")
    assert tuple(df.columns[:4]) == ("type", "start", "duration", "timeline")


def test_no_duration() -> None:
    event = ns.events.Word(start=12, duration=0, text="d", timeline="t1")
    df = pd.DataFrame([event.to_dict()])
    with pytest.warns(UserWarning, match="with null duration"):
        _ = seg.validate_events(df)


def test_segment_creator() -> None:
    df = _make_df()
    creators = seg.SegmentCreator.from_obj(df)
    assert set(creators.keys()) == {"t1", "t2"}
    segment = creators["t1"].select(start=2.5, duration=10)
    assert len(segment.ns_events) == 1
    assert segment.ns_events[0].text == "d"  # type: ignore
