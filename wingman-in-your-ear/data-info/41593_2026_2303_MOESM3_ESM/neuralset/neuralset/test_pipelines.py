# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
from pathlib import Path

import numpy as np
import pytest
from matplotlib.figure import Figure

import neuralset as ns

from .pipelines import NeuroLoader, TimeDecoding


@pytest.mark.parametrize("frequency", (100.0, 200.0))
def test_evoked(frequency: float) -> None:
    meg = ns.features.Meg(
        frequency=frequency,
        filter=(0.05, 20.0),
        baseline=(0.0, 0.5),
    )
    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    loader = NeuroLoader(
        study=study, event_type="Stimulus", start=-0.1, duration=1, neuro=meg
    )
    batch = loader.load_neuro().numpy()
    evoked = np.median(batch, 0)
    assert evoked.shape[1] == frequency
    index = np.argmax(abs(evoked).mean(0))  # largest peak
    assert index / frequency == pytest.approx(0.2, abs=0.01)


def test_neuroloader_events_query(tmp_path: Path) -> None:
    events_query = "(split == 'train') | (type == 'Meg')"
    study = ns.data.StudyLoader(name="TestMeg2023", path=tmp_path / "data")
    loader = NeuroLoader(
        study=study,
        events_query=events_query,
        event_type="Image",
        start=-0.1,
        duration=1,
        neuro=ns.features.Meg(),
    )
    events = loader.load_events()
    assert events.shape == (15, 16)
    assert events.split.dropna().unique() == ["train"]


@pytest.mark.parametrize(
    "model_name",
    [
        "Ridge",
        "RidgeCV",
        "RidgeClassifier",
        "RidgeClassifierCV",
        "DummyClassifier",
        "DummyRegressor",
    ],
)
@pytest.mark.parametrize("task", ["encode", "decode"])
def test_time_decoding(model_name, task) -> None:
    if task == "encode" and "Classifier" in model_name:
        return
    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    pipeline = TimeDecoding(
        study=study,
        model_name=model_name,
        event_type="Stimulus",
        start=-0.1,
        duration=1.0,
        task=task,
        target=ns.features.Stimulus(aggregation="trigger"),
        test_size=0.5,
        random_state=42,
    )
    scores = pipeline.run()
    if task == "encode":
        assert scores.shape == (1, 10, 306)
    else:
        assert scores.shape == (1, 10, 1)  # 1 subject, 1s @10Hz

    fig = pipeline.plot_decoding()
    assert isinstance(fig, Figure)


def test_time_decoding_with_group(caplog) -> None:
    caplog.set_level(logging.INFO)

    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    pipeline = TimeDecoding(
        study=study,
        model_name="RidgeClassifier",
        event_type="Stimulus",
        start=-0.1,
        duration=1.0,
        task="decode",
        target=ns.features.Stimulus(aggregation="trigger"),
        group=ns.features.LabelEncoder(
            event_types="Stimulus", event_field="side", aggregation="trigger"
        ),
    )
    scores = pipeline.run()
    assert "Shapes: X_train=(145, 306, 10), y_train=(145, 1)" in caplog.text
    assert "Shapes: X_test=(143, 306, 10), y_test=(143, 1)" in caplog.text
    assert "Shapes: groups_train=(145, 1), groups_test=(143, 1)" in caplog.text
    assert scores.shape == (1, 10, 1)


def test_time_decoding_with_test_query(caplog) -> None:
    caplog.set_level(logging.INFO)

    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    pipeline = TimeDecoding(
        study=study,
        model_name="RidgeClassifier",
        event_type="Stimulus",
        start=-0.1,
        duration=1.0,
        task="decode",
        target=ns.features.Stimulus(aggregation="trigger"),
        group=ns.features.LabelEncoder(
            event_types="Stimulus", event_field="split", aggregation="trigger"
        ),
        test_size=None,
        test_query="code == 1",
    )
    scores = pipeline.run()
    assert "Shapes: X_train=(215, 306, 10), y_train=(215, 1" in caplog.text
    assert "Shapes: X_test=(73, 306, 10), y_test=(73, 1)" in caplog.text
    assert "Shapes: groups_train=(215, 1), groups_test=(73, 1)" in caplog.text
    assert scores.shape == (1, 10, 1)


def test_time_decoding_stride(caplog) -> None:
    caplog.set_level(logging.INFO)

    study = ns.data.StudyLoader(name="MneSample2013", path=ns.CACHE_FOLDER)
    pipeline = TimeDecoding(
        study=study,
        model_name="RidgeClassifier",
        event_type="Meg",
        start=0.0,
        duration=1.0,
        stride=0.5,
        task="decode",
        test_size=0.2,
        target=ns.features.LabelEncoder(
            event_types="Meg", event_field="start", aggregation="trigger"
        ),
    )
    scores = pipeline.run()
    assert "Shapes: X_train=(443, 306, 10), y_train=(443, 1)" in caplog.text
    assert "Shapes: X_test=(111, 306, 10), y_test=(111, 1)" in caplog.text
    assert scores.shape == (1, 10, 1)
