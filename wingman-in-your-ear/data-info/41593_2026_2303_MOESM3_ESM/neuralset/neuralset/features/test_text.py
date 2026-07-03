# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import os
import typing as tp

import numpy as np
import pandas as pd
import pytest
import torch

import neuralset as ns
from neuralset import helpers
from neuralset.base import TimedArray
from neuralset.enhancers import AddConcatenationContext

from . import text


def _make_test_events() -> pd.DataFrame:
    sentence = 3 * ("This is a sentence for the unit tests").split(" ")
    events_list = [
        dict(
            type="Word",
            text=sentence[i],
            start=i,
            duration=i + 1,
            language="english",
            timeline="foo",
            split="train",
            sequence_id=0,
        )
        for i in range(len(sentence))
    ]
    events = pd.DataFrame(events_list)
    add_context = AddConcatenationContext()
    add_context(events)
    return events


@pytest.mark.parametrize(
    "feature_cls",
    [
        text.WordLength,
        text.WordFrequency,
        text.SpacyEmbedding,
    ],
)
def test_word_embedding(feature_cls: tp.Type[text.BaseText]) -> None:
    events = _make_test_events()
    feature = feature_cls(aggregation="sum")
    feature.prepare(events)
    events_list = helpers.extract_events(events, types=feature.event_types)
    out = feature.get_static(events_list[0])  # type: ignore
    assert isinstance(out, torch.Tensor)


def test_spacy_empty() -> None:
    events = _make_test_events()
    feature = text.SpacyEmbedding(aggregation="sum", allow_missing=True)
    feature.prepare(events)
    out = feature([], 0, 1)
    assert out.shape == (300,)


@pytest.mark.parametrize("contextualized", [True, False])
@pytest.mark.parametrize("layer", [0, 0.5, 1])
@pytest.mark.parametrize("cache_all_layers", [True, False])
@pytest.mark.parametrize("model_name", ["openai-community/gpt2", "google-t5/t5-small"])
def test_llm(
    contextualized: bool, layer: int, cache_all_layers: bool, model_name: str
) -> None:
    events = _make_test_events()
    feature = text.HuggingFaceText(
        aggregation="sum",
        layers=layer,
        contextualized=contextualized,
        cache_all_layers=cache_all_layers,
        model_name=model_name,
    )
    if hasattr(feature, "model_name"):
        assert "xl" not in feature.model_name, "Avoid large models as default"
    feature.prepare(events)
    events_list = helpers.extract_events(events, types=feature.event_types)
    out = list(feature._get_timed_arrays(events=events_list[:1], start=0, duration=1))  # type: ignore
    assert len(out) == 1
    assert isinstance(out[0], TimedArray)


@pytest.mark.parametrize("layer_aggregation", ["mean", "sum", "group_mean", None])
def test_layer_aggregation(
    layer_aggregation: tp.Literal["mean", "sum", "group_mean", None]
):
    events = _make_test_events()
    feature = text.HuggingFaceText(
        model_name="gpt2",
        layer_aggregation=layer_aggregation,
        layers=[0, 0.5, 1],
        aggregation="sum",
        token_aggregation="mean",
    )
    feature.prepare(events)
    events_list = helpers.extract_events(events, types=feature.event_types)
    out = feature(events_list[0], 0, 1)
    assert isinstance(out, torch.Tensor)
    if layer_aggregation in ["group_mean", None]:
        assert out.ndim == 2
        if layer_aggregation == "group_mean":
            assert out.shape[0] == 2  # 2 groups of layers
        else:
            assert out.shape[0] == 3  # 3 layers
    else:
        assert out.ndim == 1


def test_tfidf() -> None:
    mock_events = []
    sentences = [
        "I want to play with the cat",
        "I have a dog",
        "I want to play with the beautiful cat",
        "I am living in Brooklyn",
    ]

    for sentence in sentences:
        mock_events.append(
            {
                "type": "Sentence",
                "start": 0,
                "timeline": "",
                "duration": 0.1,
                "text": sentence,
            }
        )

    # Adding a non-Sentence event
    mock_events.append(
        {
            "type": "Image",
            "start": 0,
            "duration": None,
            "text": "",
        }
    )

    mock_events_df = pd.DataFrame(mock_events)

    feature = text.TfidfEmbedding()
    feature.prepare(mock_events_df)
    events_list = helpers.extract_events(mock_events_df, types=feature.event_types)
    out = feature.get_static(events_list[0])  # type: ignore

    assert isinstance(out, torch.Tensor)


def test_llm_explicit_error() -> None:
    feature = text.HuggingFaceText(
        aggregation="sum",
        layers=1,
        contextualized=True,
        cache_all_layers=False,
        model_name="openai-community/gpt2",
    )
    word = ns.events.Word(text="word", start=0, duration=1, timeline="x")
    with pytest.raises(ValueError):
        _ = list(feature._get_timed_arrays([word], 0, 1))


def test_dynamic_text() -> None:
    feature = text.HuggingFaceText(
        frequency=2,
        aggregation="sum",
        layers=1,
        contextualized=False,
        cache_all_layers=False,
        model_name="openai-community/gpt2",
    )
    word = ns.events.Word(text="word", start=1, duration=1, timeline="x")
    out = feature(word, start=0, duration=3).cpu().numpy()
    np.testing.assert_array_equal(out[0] != 0, [0, 0, 1, 1, 0, 0])


def _make_word() -> ns.events.Word:
    return ns.events.Word(
        text="Hello",
        start=0,
        duration=1,
        language="english",
        timeline="foo",
        context="Hello from Paris!",
    )


def test_llm_long_context() -> None:
    feature = text.HuggingFaceText(
        aggregation="sum",
        contextualized=True,
        model_name="openai-community/gpt2",
        device="cpu",
    )
    word = _make_word()
    word.context = " ".join([str(k) for k in range(1024)])
    # should work even though context is larger that 1024=maximum (~1500)
    _ = feature(word, 0, 1)


@pytest.mark.skipif(
    "IN_GITHUB_ACTION" in os.environ, reason="Models are too big for CI cache"
)
def test_bart() -> None:
    feature = text.HuggingFaceText(
        aggregation="sum",
        contextualized=True,
        model_name="facebook/bart-base",
        device="cpu",
    )
    word = _make_word()
    _ = feature(word, 0, 1)


def test_llm_pretrained() -> None:
    word = _make_word()
    outputs = [
        text.HuggingFaceText(
            aggregation="sum", contextualized=True, device="cpu", pretrained=pretrained
        )(word, 0, 1)
        for pretrained in [True, False]
    ]
    with pytest.raises(AssertionError):
        np.testing.assert_array_almost_equal(outputs[0], outputs[1])
