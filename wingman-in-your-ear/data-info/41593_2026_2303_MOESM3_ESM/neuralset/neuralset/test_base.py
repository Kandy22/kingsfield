# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import itertools
import os
import subprocess
import typing as tp
from pathlib import Path

import exca
import numpy as np
import pandas as pd
import pydantic
import pytest
import yaml

from . import base, data
from .segments import list_segments


class A(base._Module):
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("req_a",)


class B(A):
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("req_b",)


class C(B):
    pass


def test_requirements() -> None:
    assert B.requirements == ("req_a", "req_b")
    assert C.requirements == ("req_a", "req_b")


def test_frequency_yaml() -> None:
    freq = yaml.safe_dump({"data": base.Frequency(10)})
    assert freq == "data: 10.0\n"


class MyCfg(pydantic.BaseModel):
    freq: float = base.Frequency(12)
    path: Path
    infra: exca.TaskInfra = exca.TaskInfra()

    @infra.apply
    def stuff(self) -> None:
        return None


def test_frequency_exca() -> None:
    cfg = MyCfg(path=Path(__file__))
    string = cfg.infra.config(uid=True).to_yaml()
    assert "Frequency" not in string
    assert "Path" not in string


def test_data(tmp_path: Path) -> None:
    # List all events of a study as a dataframe
    events = data.StudyLoader(name="TestMeg2023", path=tmp_path).build()

    # Build a list of segments time-locked to specific events
    dset = list_segments(events, idx=events.type == "Image", start=-0.3, duration=0.5)
    assert dset

    # List all events of a study as a dataframe
    events = data.StudyLoader(name="TestFmri2023", path=tmp_path).build()

    # Build a list of segments time-locked to specific events
    dset = list_segments(
        events,
        idx=events.type == "Word",
        start=-0.3,
        duration=0.5,
    )  # noqa
    assert dset


def test_strict_overlap() -> None:
    events = [
        {
            "start": i,
            "duration": 1,
            "stop": i + 1,
            "type": "Word",
            "text": "foo",
            "timeline": "bar",
        }
        for i in range(3)
    ]
    events_df = pd.DataFrame(events)  # type : ignore
    # string overlap is now always True
    segments = list_segments(
        events_df, idx=events_df.type == "Word", start=0.0, duration=1
    )
    assert [len(s.events) for s in segments] == [1, 1, 1]


@pytest.mark.skipif("IN_GITHUB_ACTION" in os.environ, reason="No header check in CI")
def test_header() -> None:
    lines = Path(__file__).read_text("utf8").splitlines()
    header = "\n".join(itertools.takewhile(lambda l: l.startswith("#"), lines))
    assert len(header.splitlines()) == 5, f"Identified header:\n{header}"
    root = Path(__file__).parents[2]
    assert root.name == "brainai"
    # list of files to check
    tocheck = []
    for sub in ["neuralset", "neuraltrain"]:
        assert root / sub
        output = subprocess.check_output(
            ["find", str(root / sub), "-name", "*.py"], shell=False
        )
        tocheck.extend([Path(p) for p in output.decode().splitlines()])
    # add missing licenses if none already exists
    missing = []
    AUTOADD = True
    for fp in tocheck:
        if "/build/" in str(fp.relative_to(root)):
            continue
        text = Path(fp).read_text("utf8")
        if not text.startswith(header):
            if AUTOADD and not any(x in text.lower() for x in ("license", "copyright")):
                print(f"Automatically adding header to {fp}")
                Path(fp).write_text(header + "\n\n" + text, "utf8")
            missing.append(str(fp))
    if missing:
        missing_str = "\n - ".join(missing)
        raise AssertionError(
            f"Following files are/were missing standard header (see other files):\n - {missing_str}"
        )


@pytest.mark.parametrize(
    "aggreg,expected", [("sum", [0, 9, 10, 10, 1]), ("average", [0, 3, 2.5, 2.5, 1])]
)
def test_timed_array(aggreg: str, expected: list[int]) -> None:
    d = base.TimedArray(data=np.ones((2, 10)), start=10, frequency=1)
    fill = base.TimedArray(start=8, duration=12, frequency=1, aggregation=aggreg)
    fill += d
    assert fill.data.shape == (2, 12)
    np.testing.assert_array_equal(fill.data[0, :5], [0, 0, 1, 1, 1])
    # more for aggregation
    d = base.TimedArray(
        data=3 * np.ones((2, 3)), start=9, frequency=1, aggregation=aggreg
    )
    for _ in range(3):
        fill += d
    np.testing.assert_array_equal(fill.data[0, :5], expected)


@pytest.mark.parametrize(
    "start,duration,ostart,oduration,num",
    [
        (10, 10, 10, 10, 10),  # all
        (15, 10, 15, 5, 5),  # right edge
        (5, 10, 10, 5, 5),  # left edge
        (12, 6, 12, 6, 6),  # inside
        (8, 15, 10, 10, 10),  # around
        (19.9, 10, 19, 1, 1),  # right edge
        (9.1, 1, 10, 1, 1),  # left edge
        (12, 0.1, 12, 1, 1),  # mini middle
    ],
)
def test_timed_array_overlap(
    start: float, duration: float, ostart: float, oduration: float, num: int
) -> None:
    d = base.TimedArray(data=10 + np.arange(10)[None, :], start=10, frequency=1)
    o = d.overlap(start, duration)
    assert o is not None
    assert (o.start, o.duration, o.data.shape[-1]) == (ostart, oduration, num)
    np.testing.assert_equal(o.data, np.arange(o.start, o.start + o.duration)[None, :])


def test_timed_array_load_testing() -> None:
    seed = np.random.randint(2**32 - 1)
    for k in range(100):
        print(f"Seeding with {seed + k} for reproducibility")
        rng = np.random.default_rng(seed + k)
        freq = rng.uniform(0, 50)
        if freq > 1 and rng.integers(2):
            freq = int(freq)
        content = np.ones((3, 1 + rng.integers(4)))
        f = base.TimedArray(data=content, start=rng.uniform(0, 1), frequency=freq)
        start = f.start + rng.uniform(-0.1, 0.1)
        end = f.start + f.duration + rng.uniform(-0.1, 0.1)
        duration = end - start
        if duration < 0:
            duration = rng.uniform(0.1, 0.2)
        s = base.TimedArray(duration=duration, start=start, frequency=freq)
        s += f
        if f.start + f.duration < s.start or s.start + s.duration < f.start:
            assert s._overlap_slice(f.start, f.duration) is None
            assert not np.any(s.data)
        else:
            assert np.any(s.data)


def test_timed_array_case() -> None:
    out = base.TimedArray(frequency=3, start=0, duration=1.0)
    d = np.array([[0.5, 1.0, 1.5]])
    content = base.TimedArray(frequency=3.0, start=0.5, duration=1.0, data=d)
    out += content


@pytest.mark.parametrize(
    "aggreg,expected",
    [
        ("average", [0.5, 1.0]),
        ("sum", [1.0, 2.0]),
    ],
)
def test_no_freq(aggreg: str, expected: list[float]) -> None:
    out = base.TimedArray(frequency=3, start=0, duration=1.0)
    d = np.array([0.5, 1.0])
    content = base.TimedArray(frequency=0, start=0.5, duration=1.0, data=d)
    out += content
    assert out.data.shape == (2, 3)
    np.testing.assert_array_equal(out.data, [[0.0, 0.5, 0.5], [0.0, 1.0, 1.0]])
    with pytest.raises(ValueError):
        content += out
    out = base.TimedArray(start=0, frequency=0, duration=3, aggregation=aggreg)
    for _ in range(2):
        out += base.TimedArray(frequency=0, start=0.5, duration=1.0, data=d)
    np.testing.assert_array_equal(out.data, expected)


@pytest.mark.parametrize("out_freq", (0, 10))
@pytest.mark.parametrize("in_freq", (0, 10))
def test_no_duration(in_freq: float, out_freq: float) -> None:
    out = base.TimedArray(frequency=out_freq, start=0, duration=1.0)
    d = np.array([0.5, 1.0])
    if in_freq:
        d = d[..., None]
    content = base.TimedArray(frequency=0, start=0.5, duration=0, data=d)
    out += content
    norm1 = float(sum(abs(out.data.ravel())))
    assert norm1


# TODO: find a way to enable this use case where freq is approximate
# def test_approx_freq() -> None:
#     tarrays = []
#     freq = 10
#     for dur in [10, 100]:
#         data = np.random.rand(4, int(freq * dur - 1))
#         dfreq = data.shape[-1] / dur
#         tarrays.append(base.TimedArray(frequency=dfreq, start=0, duration=dur, data=data))
#     tarrays[0] += tarrays[1]
#     tarrays[1] += tarrays[0]


def test_approx_freq_brainvision() -> None:
    tarrays = []
    d = np.random.rand(4, 100)
    for freq in [120, 119.5]:
        tarrays.append(base.TimedArray(frequency=freq, start=0, data=d))
    tarrays[0] += tarrays[1]
    tarrays[1] += tarrays[0]


def test_overlap_no_duration() -> None:
    d = np.random.rand(4, 100)
    ta = base.TimedArray(frequency=100, start=0, data=d)
    sub = ta.overlap(0, 0)
    np.testing.assert_array_equal(sub.data, d[:, :1])
