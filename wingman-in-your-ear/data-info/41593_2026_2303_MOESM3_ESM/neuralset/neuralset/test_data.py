# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import collections
import concurrent.futures
import multiprocessing as mp
import os
import typing as tp
from pathlib import Path

import cloudpickle
import pandas as pd
import pydantic
import pytest

import neuralset as ns
import neuralset.enhancers as enh

from . import helpers, segments


def _check_loaded(loader: ns.data.StudyLoader) -> bool:
    if "fork" not in mp.get_start_method():
        msg = "In a non-forked subprocess, instances should not be registered yet"
        assert not ns.data.TIMELINES, msg
    _ = loader.build()
    return bool(ns.data.TIMELINES)


class DoNothing(enh.BaseEnhancer):
    name: tp.Literal["DoNothing"] = "DoNothing"
    param: str
    is_default: int = 12

    def __call__(self, events: pd.DataFrame) -> pd.DataFrame:
        return events


def test_loader(tmp_path: Path) -> None:
    loader = ns.data.StudyLoader(
        name="MneSample2013",
        path=ns.CACHE_FOLDER,
        infra={"folder": tmp_path, "mode": "force"},  # type: ignore
        enhancers=[{"name": "DoNothing", "param": "blublu-param"}],  # type: ignore
    )
    df = loader.build()
    folder = loader.infra.uid_folder()
    assert folder is not None
    # it was loaded from job
    assert isinstance(df, pd.DataFrame)
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as ex:
        job = ex.submit(_check_loaded, loader)
    assert job.result(), "Instances should have been registered at load time"
    # check signature on build infra (since infra ignores enhancers)
    cfg = loader._build_infra.config(uid=True, exclude_defaults=True)
    assert "DoNothing" in str(cfg)
    assert "blublu-param" in str(cfg)
    assert "is_default" not in str(cfg)


@pytest.mark.parametrize("cluster", ("processpool", "slurm"))
def test_loader_workers(tmp_path: Path, cluster: str) -> None:
    loader = ns.data.StudyLoader(
        name="MneSample2013",
        path=ns.CACHE_FOLDER,
        infra={"folder": tmp_path, "mode": "force", "cluster": cluster},  # type: ignore
    )
    assert loader.infra.cluster == cluster
    expected = None if cluster == "processpool" else 128
    assert loader.infra.max_jobs is expected


def test_enhancer_dict(tmp_path: Path) -> None:
    loader = ns.data.StudyLoader(
        name="MneSample2013",
        path=ns.CACHE_FOLDER,
        infra={"folder": tmp_path, "mode": "force"},  # type: ignore
        enhancers={"named_enhancer": {"name": "DoNothing", "param": "blublu-param"}},  # type: ignore
    )
    assert isinstance(loader.enhancers, collections.OrderedDict)
    _ = loader.build()
    uid = loader._build_infra.uid()
    assert "enhancers={named_enhancer=" in uid


def test_loader_v2(tmp_path: Path) -> None:
    loader = ns.data.StudyLoader(
        name="MneSample2013",
        path=ns.CACHE_FOLDER,
        infra={"folder": tmp_path},  # type: ignore
        query="index==0",
    )
    df = loader.build()
    folder = loader.infra.uid_folder()
    assert folder is not None
    if not any(f.suffix == ".csv" for f in folder.iterdir()):
        names = [f.name for f in folder.iterdir()]
        raise RuntimeError(f"Missing csv file in folder with {names}")
    # timelines can be loaded from job (timelines are registered)
    assert isinstance(df, pd.DataFrame)
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as ex:
        job = ex.submit(_check_loaded, loader)  # type: ignore
    assert job.result(), "Instances should have been registered at load time"
    # check only one folder
    names = [f.name for f in tmp_path.iterdir()]
    if len(names) > 1:
        raise RuntimeError(f"Only one cache folder should have been created, got {names}")
    assert names[0] == "StudyLoader,0-v3,MneSample2013"
    names = [f.name for f in (tmp_path / names[0]).iterdir()]
    if len(names) != 2:
        raise RuntimeError(f"Only 2 infra folders should have been created, got {names}")
    # test version
    clone = loader.infra.clone_obj()
    assert clone.infra.version == loader.infra.version
    # test pickling
    string = cloudpickle.dumps(loader)
    unpickled = cloudpickle.loads(string)
    assert unpickled._build_infra.version == loader.infra.version
    # subjects
    subjects = {"MneSample2013/sample"}
    assert set(loader.study_summary().subject.unique()) == subjects
    assert set(df.subject.unique()) == subjects


@pytest.mark.parametrize(
    "name",
    (
        "Stuff123",
        "stuff1234",
        "xStuff1234",
        "Stuff12345",
        "Stuff1234Bolds",
        "Stuff1234Bol",
        "Stuff1234Mold",
    ),
)
def test_validation_study_name_error(name: str) -> None:
    with pytest.raises(ValueError):
        ns.data._validate_study_name(name)


@pytest.mark.parametrize("name", ("Name1234", "Name1234Bold", "Name1234Meg"))
def test_validation_study_name_correct(name: str) -> None:
    ns.data._validate_study_name(name)


class FakeData2222(ns.data.BaseData):
    # study/class level
    device: tp.ClassVar[str] = "Meg"
    run: int

    @classmethod
    def _download(cls, path: Path) -> None:
        for subject in [12, 13]:
            for run in range(2):
                ss_dir = path / f"sub-{subject}" / f"run-{run}"
                ss_dir.mkdir(parents=True, exist_ok=True)
                tmp_file = ss_dir / "tmp_fakedata2222.txt"
                tmp_file.touch()

    @classmethod
    def _iter_timelines(cls, path: str | Path) -> tp.Iterator["FakeData2222"]:
        for run in range(2):
            for subject in [12, 13]:
                yield FakeData2222(subject=str(subject), run=run, path=path)

    def _load_events(self) -> pd.DataFrame:
        data = {
            "type": "Motor",
            "start": 0,
            "duration": 12,
            "limb": "leg",
            "stuff": True,
        }
        return pd.DataFrame([data])


def test_loader_on_external_study(tmp_path: Path) -> None:
    ns.data.StudyLoader(name="FakeData2222", path=tmp_path)
    with pytest.raises(pydantic.ValidationError):  # (does not exist)
        ns.data.StudyLoader(name="FakeData2223", path=tmp_path)


def test_loader_download(tmp_path: Path) -> None:
    FakeData2222.download(path=tmp_path)
    for subject in [12, 13]:
        for run in range(2):
            ss_dir = tmp_path / f"sub-{subject}" / f"run-{run}"
            tmp_file = ss_dir / "tmp_fakedata2222.txt"
            assert tmp_file.is_file()
            assert ss_dir.is_dir()
            assert oct(os.stat(ss_dir).st_mode & 0o777) == "0o777"
    assert oct(os.stat(tmp_path).st_mode & 0o777) == "0o777"


def test_loader_export() -> None:
    loader = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    # fails with inf cast as int
    ns.data.StudyLoader(**loader.model_dump())


def test_multi_study_loader() -> None:
    loader = ns.data.MultiStudyLoader(
        names=["MneSample2013", "FakeData2222"],
        path=ns.CACHE_FOLDER,
        query="timeline_index==0",
    )
    df = loader.build()
    assert len(loader.study_summary()) == 2
    assert len(df.study.unique()) == 2
    assert len(df.subject.unique()) == 2


def test_study_loader_summary_and_build(tmp_path: Path) -> None:
    loader = ns.data.StudyLoader(
        name="FakeData2222", query="subject_index < 1", path=tmp_path
    )
    summary = loader.study_summary()  # filtered summary
    assert tuple(summary.subject_index) == (0, 0)
    summary = loader.study_summary(apply_query=False)
    assert tuple(summary.subject_index) == (0, 1, 0, 1)
    assert tuple(summary.timeline_index) == (0, 1, 2, 3)
    assert tuple(summary.subject_timeline_index) == (0, 0, 1, 1)
    # export
    out = loader.build()
    assert "limb" in out.columns
    segs = segments.list_segments(out, out.type == "Motor")
    trigger = segs[0]._trigger
    assert isinstance(trigger, dict)
    assert "limb" in ns.events.Event.from_dict(trigger).extra
    # back and forth
    events = [ns.events.Event.from_dict(d) for d in out.itertuples(index=False)]
    out2 = pd.DataFrame([e.to_dict() for e in events], columns=out.columns)
    pd.testing.assert_frame_equal(out2, out)


def test_extract_events(tmp_path: Path) -> None:
    loader = ns.data.StudyLoader(
        name="FakeData2222", query="subject_index < 1", path=tmp_path
    )
    out = loader.build()
    events1 = helpers.extract_events(out)
    segs = segments.list_segments(out, out.type == "Motor")
    events2 = helpers.extract_events(segs)
    assert len(events1) > 1
    assert len(events1) == len(events2)
    # other options
    assert len(helpers.extract_events(events1[0])) == 1
    assert len(helpers.extract_events(events1[0].to_dict())) == 1
    assert len(helpers.extract_events(events1)) == len(events1)
    # filtering
    assert len(helpers.extract_events(out, types="Motor")) == len(events1)
    assert not helpers.extract_events(out, types="Image")


@pytest.mark.parametrize("cache_all_timelines", (True, False))
def test_loader_cache_all_timelines(tmp_path: Path, cache_all_timelines: bool) -> None:
    loader = ns.data.StudyLoader(
        name="MneSample2013",
        path=ns.CACHE_FOLDER,
        infra={"folder": tmp_path},  # type: ignore
        query="index==0",
        cache_all_timelines=cache_all_timelines,
    )
    _ = loader.build()
    keys = tuple(loader._build_infra.cache_dict)
    assert keys == ("None" if cache_all_timelines else loader.query,)


class Xp(pydantic.BaseModel):
    study: ns.data.StudyLoader
    infra: ns.infra.TaskInfra = ns.infra.TaskInfra()

    @infra.apply
    def build(self) -> pd.DataFrame:
        # assert self.study.infra.folder == self.study._build_infra.folder
        return self.study.build()


def test_xp(tmp_path: Path) -> None:
    xp = Xp(
        infra={"folder": tmp_path / "xp", "cluster": "local"},  # type: ignore
        study=dict(  # type: ignore
            name="MneSample2013",
            path=ns.CACHE_FOLDER,
            infra={"folder": tmp_path / "study"},
        ),
    )
    # test pickling
    string = cloudpickle.dumps(xp)
    unpickled = cloudpickle.loads(string)
    assert unpickled.study._build_infra.version == xp.study.infra.version
    assert unpickled.study._build_infra._infra_method.infra_name
    assert "path" in xp.study._exclude_from_cls_uid()
    # run it
    xp.build()
    subs = list((tmp_path / "study").iterdir())
    assert len([x.name for x in subs]) == 1
    folder = subs[0]
    subnames = [x.name for x in folder.iterdir()]
    assert len(subnames) == 2, "A cache is missing (hidden infra has lost its params?)"
