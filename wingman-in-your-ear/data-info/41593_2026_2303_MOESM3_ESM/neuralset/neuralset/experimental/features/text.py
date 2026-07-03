# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import shutil
import typing as tp
from pathlib import Path

import numpy as np
import pandas as pd
import pydantic
import torch

import neuralset as ns
from neuralset.features.base import BaseStatic
from neuralset.features.text import BaseText, HuggingFaceText, SpacyEmbedding
from neuralset.infra import MapInfra

# pylint: disable=attribute-defined-outside-init
# pylint: disable=unused-variable


class FastTextEmbedding(BaseText):
    """
    Get word embedding from FastText.
    """

    name: tp.Literal["FastTextEmbedding"] = "FastTextEmbedding"
    event_types: str | tp.Tuple[str, ...] = "Word"
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("fasttext",)
    model_folder: str
    LANGUAGES: tp.ClassVar[tp.Dict[str, str]] = dict(
        english="en", french="fr", spanish="es", dutch="nl"
    )

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        path = Path(f"{self.model_folder}/cc.{self.LANGUAGES[self.language]}.300.bin")
        if not path.exists():
            from fasttext.util import download_model  # type: ignore

            download_model(self.LANGUAGES[self.language])
            # move to the right folder
            shutil.move(f"cc.{self.LANGUAGES[self.language]}.300.bin", path)

    @property
    def model(self) -> tp.Any:
        if not hasattr(self, "_model"):
            from fasttext import load_model  # type: ignore

            fp = f"{self.model_folder}/cc.{self.LANGUAGES[self.language]}.300.bin"
            self._model = load_model(fp)
        return self._model

    def get_embedding(self, text: str) -> np.ndarray:
        vector = self.model.get_word_vector(text)
        return vector


class ClosestWordEmbedding(BaseStatic):
    """
    Get closest embedding from a given vocabulary
    """

    name: tp.Literal["ClosestWordEmbedding"] = "ClosestWordEmbedding"
    event_types: str | tp.Tuple[str, ...] = "Word"
    vocabulary_size: int = 1000
    language: str = "english"

    word_embedder: tp.Union[SpacyEmbedding, FastTextEmbedding, HuggingFaceText] = (
        pydantic.Field(discriminator="name")
    )
    infra: MapInfra = MapInfra(version="1")

    LANGUAGES: tp.ClassVar[tp.Dict[str, str]] = dict(
        english="en", french="fr", spanish="es", dutch="nl"
    )
    _vocabulary: tp.List[str] = pydantic.PrivateAttr()
    _vocabulary_embeddings: torch.Tensor = pydantic.PrivateAttr()

    def _exclude_from_cache_uid(self) -> tp.List[str]:
        return super()._exclude_from_cache_uid() + ["duration", "frequency"]

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        self.event_types = self.word_embedder.event_types

    def prepare(self, obj: pd.DataFrame) -> None:
        from wordfreq import top_n_list

        from neuralset import helpers

        events: list[ns.events.Word]
        events = helpers.extract_events(obj, types=self._event_types_helper)  # type: ignore
        self.word_embedder.prepare(events)

        self._vocabulary = top_n_list(
            self.LANGUAGES.get(self.language, self.language), self.vocabulary_size
        )
        embeddings = []
        for w in self._vocabulary:
            event = ns.events.Word(start=0, duration=1, text=w, timeline="foo")
            embeddings.append(self.word_embedder.get_static(event))  # type: ignore
        self._vocabulary_embeddings = torch.stack(embeddings)
        super().prepare(events)

    @infra.apply(
        item_uid=lambda event: str(event.text),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
        cache_type="MemmapArrayFile",
    )
    def _get_data(self, events: tp.List[ns.events.Word]) -> tp.Iterator[int]:
        if not hasattr(self, "_vocabulary_embeddings"):
            raise ValueError("No vocabulary found. Please call prepare method first.")
        embed = self.word_embedder.get_static
        embeddings = torch.stack([embed(event) for event in events])  # type: ignore
        distances = torch.cdist(embeddings, self._vocabulary_embeddings)
        closest_idx = distances.argmin(dim=1)
        yield from closest_idx

    def get_closest_word(self, word: str) -> str:
        word_event = ns.events.Word(text=word, start=0, timeline="foo")
        idx = next(self._get_data([word_event]))
        return self._vocabulary[idx]

    def get_static(self, event: ns.events.Word) -> torch.Tensor:
        idx = next(self._get_data([event]))
        return self._vocabulary_embeddings[idx]
