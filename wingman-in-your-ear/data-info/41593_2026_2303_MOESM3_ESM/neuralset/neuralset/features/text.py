# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import tempfile
import typing as tp
from abc import abstractmethod

import numpy as np
import pandas as pd
import pydantic
import torch
from exca import MapInfra
from exca.utils import environment_variables
from torch import nn
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

import neuralset as ns
from neuralset import utils
from neuralset.base import TimedArray
from neuralset.features.base import BaseStatic, HuggingFaceMixin

# pylint: disable=attribute-defined-outside-init
# pylint: disable=unused-variable
DataframeOrEventsOrSegments = (
    pd.DataFrame | tp.Sequence[ns.events.Event] | tp.Sequence[ns.segments.Segment]
)


class BaseText(BaseStatic):
    """
    Base class for text features.
    """

    language: str = "english"
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("Levenshtein",)

    # for precomputing/caching
    infra: MapInfra = MapInfra(version="v5")

    def _exclude_from_cache_uid(self) -> tp.List[str]:
        return super()._exclude_from_cache_uid() + ["duration", "frequency"]

    @infra.apply(
        item_uid=lambda event: str(event.text),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
        cache_type="MemmapArrayFile",
    )
    def _get_data(self, events: tp.List[ns.events.Text]) -> tp.Iterator[np.ndarray]:
        if len(events) > 1:
            events = tqdm(events, desc="Computing word embeddings")  # type: ignore
        for event in events:
            yield self.get_embedding(event.text)

    def get_static(self, event: ns.events.Text) -> torch.Tensor:
        latent = torch.from_numpy(next(self._get_data([event])))
        return latent

    @abstractmethod
    def get_embedding(self, text: str) -> np.ndarray:
        raise NotImplementedError


class WordLength(BaseText):
    """
    Get word length.
    """

    name: tp.Literal["WordLength"] = "WordLength"
    event_types: tp.Literal["Word"] = "Word"

    def get_embedding(self, text: str) -> np.ndarray:
        return np.array([len(text)])


class WordFrequency(BaseText):
    """
    Get word frequency from wordfreq package.
    """

    name: tp.Literal["WordFrequency"] = "WordFrequency"
    event_types: tp.Literal["Word"] = "Word"
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("wordfreq",)
    LANGUAGES: tp.ClassVar[tp.Dict[str, str]] = dict(
        english="en", french="fr", spanish="es", dutch="nl", chinese="zh"
    )

    def get_embedding(self, text: str) -> np.ndarray:
        from wordfreq import zipf_frequency  # noqa

        value = zipf_frequency(text, self.LANGUAGES.get(self.language, self.language))
        return np.array([value])


class TfidfEmbedding(BaseText):
    """
    Get TF-IDF embeddings for Sentence events.
    """

    name: tp.Literal["TfidfEmbedding"] = "TfidfEmbedding"
    event_types: str | tp.Tuple[str, ...] = "Sentence"
    max_features: int = 5000
    _vectorizer: None = pydantic.PrivateAttr(None)

    @property
    def vectorizer(self) -> tp.Any:
        from sklearn.feature_extraction.text import TfidfVectorizer

        if self._vectorizer is None:
            self._vectorizer = TfidfVectorizer(
                max_features=self.max_features, stop_words=self.language
            )
        return self._vectorizer

    def prepare(self, obj: DataframeOrEventsOrSegments) -> None:
        from neuralset import helpers

        events: list[ns.events.Word]
        events = helpers.extract_events(obj, types=self._event_types_helper)  # type: ignore
        texts = [event.text for event in events]
        self.vectorizer.fit_transform(texts)
        super().prepare(events)

    def get_embedding(self, text: str) -> np.ndarray:
        if self._vectorizer is None:
            msg = "The vectorizer is not fitted. Please call the prepare method before."
            raise ValueError(msg)
        vector = self.vectorizer.transform([text]).toarray()
        return vector.squeeze(0)


class SpacyEmbedding(BaseText):
    """
    Get word embedding from spacy.
    """

    name: tp.Literal["SpacyEmbedding"] = "SpacyEmbedding"
    event_types: tp.Literal["Word"] = "Word"
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("spacy>=3.8.2",)
    LANGUAGES: tp.ClassVar[tp.Dict[str, str]] = dict(
        english="en_core_web_lg",
        french="fr_core_news_lg",
        spanish="es_core_news_lg",
        japanese="ja_core_news_lg",
        chinese="zh_core_web_lg",
    )

    def get_embedding(self, text: str) -> np.ndarray:
        model = utils.get_spacy_model(model=self.LANGUAGES[self.language])  # lru cached
        vector = model(text).vector
        return vector


class SonarEmbedding(BaseText):
    """
    Get embeddings from sonar: https://arxiv.org/abs/2308.11466
    """

    name: tp.Literal["SonarEmbedding"] = "SonarEmbedding"
    event_types: tp.Literal["Sentence"] = "Sentence"

    requirements: tp.ClassVar[tp.Tuple[str, ...]] = (
        "fairseq2",
        "sonar-space",
    )
    LANGUAGES: tp.ClassVar[tp.Dict[str, str]] = dict(en="eng_Latn", english="eng_Latn")

    @property
    def model(self) -> nn.Module:
        if not hasattr(self, "_model"):
            from sonar.inference_pipelines.text import (  # type: ignore
                TextToEmbeddingModelPipeline,
            )

            self._model = TextToEmbeddingModelPipeline(
                encoder="text_sonar_basic_encoder", tokenizer="text_sonar_basic_encoder"
            )
            self._model.eval()
        return self._model

    @torch.no_grad()
    def get_embedding(self, text: str) -> np.ndarray:
        vector = self.model.predict([text], source_lang=self.LANGUAGES.get(self.language, self.language))  # type: ignore
        return vector.squeeze(0).cpu().numpy()


class SentenceTransformer(BaseText):
    """
    Get embeddings from SentenceTransformers: https://huggingface.co/sentence-transformers.
    """

    name: tp.Literal["SentenceTransformer"] = "SentenceTransformer"
    event_types: tp.Literal["Sentence"] = "Sentence"
    model_name: str = "all-mpnet-base-v2"

    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("sentence_transformers",)

    @property
    def model(self) -> nn.Module:
        if not hasattr(self, "_model"):
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
        return self._model

    @torch.no_grad()
    def get_embedding(self, text: str) -> np.ndarray:
        vector = self.model.encode([text])  # type: ignore
        return vector.squeeze(0)


class TextDataset(Dataset):
    """
    Dataset for contextual embeddings.
    """

    def __init__(self, events: tp.List[ns.events.Word]):
        self.events = events

    def __len__(self):
        return len(self.events)

    def __getitem__(self, idx):
        sel = self.events[idx]
        return sel.text, sel.context


class HuggingFaceText(BaseStatic, HuggingFaceMixin):
    """
    Get embeddings from HuggingFace language models.
    This feature can be applied to any kind of event which has a text attribute: Word, Sentence, etc.

    Parameters
    ----------
    batch_size: int
        Batch size for the language model.
    contextualized: bool
        If True, the context of the event is used to compute the embeddings.

    Note
    ----
    The tokenizer truncates the input to the maximum size specified by the model
    """

    name: tp.Literal["HuggingFaceText"] = "HuggingFaceText"
    model_name: str = "openai-community/gpt2"

    # class attributes
    event_types: tp.Literal["Word", "Sentence"] = "Word"
    requirements: tp.ClassVar[tp.Tuple[str, ...]] = ("transformers>=4.29.2",)
    infra: MapInfra = MapInfra(
        timeout_min=25,
        gpus_per_node=1,
        cpus_per_task=10,
        min_samples_per_job=4096,
        version="v5",
    )

    # feature attributes
    batch_size: int = 32
    contextualized: bool = False
    pretrained: bool = True

    # initialized later
    _model: nn.Module = pydantic.PrivateAttr()
    _tokenizer: nn.Module = pydantic.PrivateAttr()
    _pad_id: int = pydantic.PrivateAttr()

    @classmethod
    def _exclude_from_cls_uid(cls) -> tp.List[str]:
        return (
            ["batch_size"]
            + BaseStatic._exclude_from_cls_uid()
            + HuggingFaceMixin._exclude_from_cls_uid()
        )

    def _exclude_from_cache_uid(self) -> tp.List[str]:
        excluded = ["frequency", "duration", "batch_size"]
        return (
            excluded
            + BaseStatic._exclude_from_cache_uid(self)
            + HuggingFaceMixin._exclude_from_cache_uid(self)
        )

    @property
    def model(self) -> nn.Module:
        if not hasattr(self, "_model"):
            from transformers import AutoModel, AutoTokenizer

            kwargs: dict[str, tp.Any] = {}
            if self.model_name.lower().startswith("microsoft/phi"):
                kwargs["trust_remote_code"] = True
            # make sure to truncate on the left side!
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name, truncation_side="left", **kwargs
            )
            Model = AutoModel
            if "t5" in self.model_name or "bert" in self.model_name:
                from transformers import AutoModelForTextEncoding

                Model = AutoModelForTextEncoding  # type: ignore
            elif "Phi-3" in self.model_name:
                from transformers import AutoModelForCausalLM

                Model = AutoModelForCausalLM  # type: ignore
            elif "Llama-3.2-11B-Vision" in self.model_name:
                from transformers import MllamaForConditionalGeneration

                Model = MllamaForConditionalGeneration  # type: ignore
            # instantiate
            if self.device == "accelerate":
                kwargs = {"device_map": "auto", "torch_dtype": torch.float16}
            self._model = Model.from_pretrained(self.model_name, **kwargs)
            if not self.pretrained:
                # device_map = {name: param.device for name, param in self._model.named_parameters()}
                self._model = Model.from_config(self._model.config)
                if self.device == "accelerate":
                    # dump and reload to use device_map="auto"
                    with tempfile.TemporaryDirectory() as tmp:
                        self._model.save_pretrained(tmp)  # type: ignore
                        self._model = Model.from_pretrained(tmp, **kwargs)
            if self.device != "accelerate":
                self._model.to(self.device)
            self._model.eval()
            # tokens
            if self._tokenizer.pad_token is None:
                # previously:
                # self._tokenizer.add_special_tokens({"pad_token": "[PAD]"})
                # self._model.resize_token_embeddings(len(self._tokenizer))
                # simpler to use existing EOS token:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            self._pad_id = self.tokenizer.eos_token_id  # type: ignore
        return self._model

    @property
    def tokenizer(self) -> nn.Module:
        self.model
        return self._tokenizer

    def _get_timed_arrays(
        self, events: list[ns.events.Word], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        # optimized fetch of multiple events compared to individual get_static calls:
        for event, latent in zip(events, self._get_data(events)):
            if self.cache_all_layers:
                latent = self._aggregate_layers(latent)
            ta = TimedArray(
                frequency=0,
                duration=event.duration,
                start=event.start,
                data=latent,
            )
            yield ta

    @infra.apply(
        item_uid=lambda event: f"{event.text}_{event.context}",
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
        cache_type="MemmapArrayFile",
    )
    def _get_data(self, events: tp.List[ns.events.Word]) -> tp.Iterator[np.ndarray]:
        dataset = TextDataset(events)
        dloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=False)

        # Processing the data in batches
        if len(dloader) > 1:
            dloader = tqdm(dloader, desc="Computing word embeddings")  # type: ignore
        device = "auto" if self.device == "accelerate" else self.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        for target_words, context in dloader:
            # tokenize context
            with environment_variables(TOKENIZERS_PARALLELISM="false"):
                text = context if self.contextualized else target_words
                if isinstance(text, tuple):
                    # temporary fix for tokenizers==0.20.2
                    # https://github.com/huggingface/tokenizers/issues/1672
                    text = list(text)
                if not all(text):
                    msg = f"Empty text or context for target_words {target_words!r}"
                    raise ValueError(msg)
                inputs = self.tokenizer(
                    text,
                    add_special_tokens=False,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,  # beware to have set truncation_side="left" in init
                ).to(device)
            with torch.no_grad():
                outputs = self.model(**inputs, output_hidden_states=True)
            if "hidden_states" in outputs:
                states = outputs.hidden_states
            else:  # bart (encoder/decoder)
                states = outputs.encoder_hidden_states + outputs.decoder_hidden_states
            hidden_states = torch.stack([layer.cpu() for layer in states])
            n_layers, n_batch, n_tokens, n_dims = hidden_states.shape  # noqa

            # -- for each target word, remove padding, and sum hidden states
            for i, target_word in enumerate(target_words):
                # select batch element
                hidden_state = hidden_states[:, i]  # n_layers x tokens x embd

                # count number of pads
                n_pads = sum(inputs["input_ids"][i].cpu().numpy() == self._pad_id)

                # remove pads
                if n_pads:
                    hidden_state = hidden_state[:, :-n_pads]

                # sum all token that belong to the target word
                if self.contextualized:
                    word_state = hidden_state[:, -len(target_word) :]
                else:
                    word_state = hidden_state
                # aggregate in cuda for smaller data transfer:
                word_state = self._aggregate_tokens(word_state)
                out = word_state.cpu().numpy()
                if not self.cache_all_layers:
                    out = self._aggregate_layers(out)
                yield out
