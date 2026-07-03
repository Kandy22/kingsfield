# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing as tp
import warnings

import matplotlib.pyplot as plt
import mne
import numpy as np
import pandas as pd
import pydantic
import torch
import tqdm
from matplotlib.figure import Figure
from scipy.stats import pearsonr
from sklearn import dummy, linear_model
from sklearn.base import ClassifierMixin, RegressorMixin
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import neuralset as ns
from neuralset.events import Event
from neuralset.helpers import prepare_features
from neuralset.utils import train_test_split_by_group

logger = logging.getLogger(__name__)


class NeuroLoader(pydantic.BaseModel):
    """
    A flexible pipeline for loading neuro data for a given experiment.

    Parameters
    ----------
    study: ns.data.StudyLoader
        The config of the study: an instance of ns.data.StudyLoader.
    events_query: str, optional
        DataFrame query to e.g. select a subset of the events.
    neuro: ns.features.FeatureConfig, optional
        The neuro feature: an instance of ns.features.Meg, ns.features.Eeg, ns.features.Fmri, or ns.features.Ieeg.
        By default, select type automatically based on the study.
    event_type: str
        The type of event to use as timelocks.
    start: float
        The start of the segments relative to the word onsets.
        Default: -0.5.
    duration: float
        The duration of the segments.
        Default: 3.0.
    stride: float, optional
        If provided, extract sliding segments with the specified stride.
    """

    model_config = pydantic.ConfigDict(extra="forbid")
    name: tp.Literal["NeuroLoader"] = "NeuroLoader"

    study: ns.data.StudyLoader
    events_query: str | None = None
    neuro: ns.features.FeatureConfig | ns.features.BaseFeature | tp.Literal["auto"] = (
        "auto"
    )
    event_type: str
    start: float = -0.5
    duration: float = 3.0
    stride: float | None = None

    _neuro_type: str = pydantic.PrivateAttr()

    def model_post_init(self, __context: tp.Any) -> None:
        super().model_post_init(__context)
        if self.event_type != "auto" and self.event_type not in Event._CLASSES:
            raise ValueError(f"Event type {self.event_type} not found in events")

    def load_events(self) -> pd.DataFrame:
        """
        Load the events.
        """
        logger.info("Loading events...")
        events = self.study.build()
        if self.events_query is not None:
            events = events.query(self.events_query)

        assert (
            self.event_type in events.type.unique()
        ), f"Event type {self.event_type} not found in events"
        neuro_types = list(
            set(events.type) & {"Eeg", "Emg", "Fmri", "Fnirs", "Meg", "Ieeg"}
        )

        if self.neuro == "auto":
            assert (
                len(neuro_types) == 1
            ), "There are multiple neuro types, cannot pick automatically."
            self._neuro_type = neuro_types[0]

            infra_config = {"folder": self.study.infra.folder, "keep_in_ram": True}
            if self._neuro_type == "Fmri":
                self.neuro = ns.features.Fmri(
                    detrend=True,
                    mesh="fsaverage5",
                    infra=infra_config,  # type: ignore
                )
            else:
                self.neuro = getattr(ns.features, self._neuro_type)(
                    frequency=10.0,
                    filter=(0.1, 40.0),
                    clamp=20.0,
                    scaler="RobustScaler",
                    infra=infra_config,
                )
        else:
            neuro_name = self.neuro.name  # type: ignore
            if neuro_name not in neuro_types:
                msg = (
                    f"The specified neuro feature {neuro_name} does not match "
                    f"available events: {neuro_types}."
                )
                warnings.warn(msg)
            self._neuro_type = neuro_name

        return events

    def load_neuro(self) -> torch.Tensor:
        """
        Load the neuro data.
        """
        events = self.load_events()
        self.neuro.prepare(events)  # type: ignore

        logger.info("Creating segments...")
        segments = ns.segments.list_segments(
            events,
            idx=events.type == self.event_type,
            start=self.start,
            duration=self.duration,
            stride=self.stride,
            stride_drop_incomplete=False,
        )
        dataset = ns.SegmentDataset(
            features={"neuro": self.neuro},  # type: ignore
            segments=segments,
            remove_incomplete_segments=True,
        )

        logger.info("Gathering all neuro data...")
        neuro_batch = dataset.as_one_batch().data["neuro"]

        return neuro_batch

    def get_evoked(self):

        events = self.load_events()
        batch = self.load_neuro()
        assert self._neuro_type in [
            "Eeg",
            "Meg",
            "Ieeg",
        ], "Evoked response only works for EEG/MEG data"

        row = events.query(f'type=="{self._neuro_type}"').iloc[0]
        first_event = ns.events.BaseDataEvent.from_dict(row)
        raw = next(self.neuro._get_data([first_event]))

        with raw.info._unlock():
            raw.info["sfreq"] = self.neuro.frequency
        epochs = mne.EpochsArray(
            batch,
            info=raw.info,
            events=None,
            verbose=False,
            tmin=self.start,
        )
        evoked = epochs.average(method="median")
        return evoked

    def plot_evoked(self, mne_kwargs: tp.Optional[dict[str, tp.Any]] = None) -> Figure:
        evoked = self.get_evoked()
        kwargs = mne_kwargs or {}
        fig = evoked.plot_joint(**kwargs)
        return fig

    def plot_topomap(
        self, times=None, mne_kwargs: tp.Optional[tp.Dict[str, tp.Any]] = None
    ) -> Figure:
        evoked = self.get_evoked()
        kwargs = mne_kwargs or {}
        if times is None:
            times = np.linspace(self.start, self.start + self.duration, 9)[:-1]
        fig = evoked.plot_topomap(times=times, **kwargs)
        return fig


class TimeDecoding(NeuroLoader):
    """A flexible pipeline for decoding/encoding a target feature from/to neuro data.

    Parameters
    ----------
    target: ns.features.FeatureConfig, optional
        The target feature.
        By default, select based on the event type.
    group: ns.features.LabelEncoder, optional
        Categorical feature used to split data into train and test sets (e.g., subjects).
    model: str, optional
        Whether to use a RidgeCV (regression), a RidgeClassifierCV (classification) or a
        DummyClassifier (to evaluate chance-level on a classification task).
    alphas: list[float], optional
        If using a model with embedded cross-validation (e.g. RidgeCV, RidgeClassifierCV),
        regularization values to include in the grid search.
    task: str, optional
        Whether to decode (predict the target from the neuro data) or encode (predict the neuro
        data from the target).
    multi_subject: bool, optional
        If True, fit model on all available subjects at once.
    test_size: float, optional
        Fraction of the data to keep for testing.
    test_query: str, optional
        DataFrame query to create a "split" column that can be used by the group feature. Requires
        group to be defined, and cannot be used with test_size.
    random_state: int, optional
        Random state for train/test set split.
    shuffle_target: bool
        If True, shuffle targets such that the model performs at chance level.
    """

    name: tp.Literal["TimeDecoding"] = "TimeDecoding"  # type: ignore

    target: ns.features.FeatureConfig | tp.Literal["auto"] = "auto"
    group: ns.features.LabelEncoder | None = None
    model_name: tp.Literal[
        # Regressors
        "Ridge",
        "RidgeCV",
        "DummyRegressor",
        # Classifiers
        "RidgeClassifier",
        "RidgeClassifierCV",
        "DummyClassifier",
    ] = "RidgeCV"
    alphas: list[float] | None = None
    task: tp.Literal["encode", "decode"] = "decode"
    multi_subject: bool = False
    test_size: float | None = 0.2
    test_query: str | None = None
    random_state: int | None = 42
    shuffle_target: bool = False

    infra: ns.infra.MapInfra = ns.infra.MapInfra()
    model_config = pydantic.ConfigDict(extra="forbid")

    _features: dict[str, ns.features.BaseFeature] = pydantic.PrivateAttr()

    def model_post_init(self, __context: tp.Any) -> None:
        super().model_post_init(__context)
        if self.event_type != "auto" and self.event_type not in Event._CLASSES:
            raise ValueError(f"Event type {self.event_type} not found in events")
        assert not (self.task == "encode" and "Classifier" in self.model_name)

        if self.test_query is not None:
            if self.test_size is not None:
                raise ValueError("Cannot use both test_query and test_size.")
            if self.group is None:
                raise ValueError("Cannot use test_query without group.")

    def prepare(self) -> pd.DataFrame:

        events = self.load_events()
        target: ns.features.BaseFeature
        if self.target == "auto":
            match self.event_type:
                case "Word":
                    languages = events[events.type == "Word"].language.unique()
                    assert len(languages) == 1, "There are multiple languages"
                    language = languages[0]
                    if not isinstance(language, str):
                        language = "english"
                    target = ns.features.WordFrequency(
                        language=language, aggregation="trigger"
                    )
                case "Sentence":
                    target = ns.features.HuggingFaceText(
                        model_name="t5-large",
                        event_types="Sentence",
                        aggregation="trigger",
                    )
                case "Image":
                    target = ns.features.HugggingFaceImage(aggregation="trigger")
                case "Stimulus":
                    target = ns.features.Stimulus(aggregation="trigger")
                case _:
                    raise NotImplementedError(
                        f"Event type {self.event_type} not implemented in auto mode"
                    )
        elif isinstance(self.target, ns.features.BaseFeature):
            target = self.target

        logger.info("Preparing features...")
        prepare_features([self.neuro, target], events)  # type: ignore

        assert isinstance(self.neuro, ns.features.BaseFeature)
        self._features = {"neuro": self.neuro, "target": target}

        if self.test_query is not None:
            events.loc[events.type == self.event_type, "split"] = 0
            test_inds = events.query(self.test_query).index
            events.loc[test_inds, "split"] = 1

        if self.group is not None:
            logger.info("Preparing group feature...")
            self.group.prepare(events)
            self._features["group"] = self.group

        return events

    def _get_subjects(self) -> list[str]:
        return (
            ["all"]
            if self.multi_subject
            else self.study.study_summary().subject.unique().tolist()
        )

    def _get_subject_dataset(
        self, events: pd.DataFrame, subject: str
    ) -> ns.SegmentDataset:
        if subject == "all":
            subject_events = events
        else:
            subject_events = events.query(f"subject == '{subject}'")
        logger.info("Creating segments...")
        segments = ns.segments.list_segments(
            subject_events,
            idx=subject_events.type == self.event_type,
            start=self.start,
            duration=self.duration,
            stride=self.stride,
        )
        logger.info("Creating dataset...")
        dataset = ns.SegmentDataset(
            features=self._features,  # type: ignore
            segments=segments,
            remove_incomplete_segments=True,
        )
        return dataset

    def _get_X_y_group_from_dataset(
        self,
        dataset: ns.SegmentDataset,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        one_batch = dataset.as_one_batch()
        X, y = one_batch.data["neuro"].numpy(), one_batch.data["target"].numpy()
        groups = one_batch.data["group"].numpy() if self.group is not None else None
        return X, y, groups

    @infra.apply(item_uid=str)
    def _run_on_subject(self, subjects: list[str]) -> tp.Iterator[np.ndarray]:
        events = self.load_events()
        for subject in subjects:
            logger.info(f"Running pipeline for subject={subject}...")
            dataset = self._get_subject_dataset(events, subject)

            logger.info("Getting X and y from dataset...")
            X, y, groups = self._get_X_y_group_from_dataset(dataset)

            if "Classifier" in self.model_name:
                class_distr = pd.Series(y.ravel()).value_counts().to_dict()
                logger.info(f"# examples per class: {class_distr}")

            logger.info(f"Computing scores for subject={subject}...")
            scores = self._get_score(X, y, groups=groups)
            yield scores

    @staticmethod
    def _pearsonr_corr(x: np.ndarray, y: np.ndarray) -> float:
        return pearsonr(x, y)[0]  # Return correlation only

    def _get_model_and_metric(
        self,
    ) -> tuple[RegressorMixin | ClassifierMixin, tp.Callable]:
        alphas = np.logspace(-2, 8, 7) if self.alphas is None else self.alphas
        kwargs: dict = {"alphas": alphas} if "CV" in self.model_name else {}
        if self.model_name.startswith("RidgeClassifier"):
            kwargs["class_weight"] = "balanced"
        model = getattr(
            dummy if "Dummy" in self.model_name else linear_model, self.model_name
        )(**kwargs)
        pipeline = make_pipeline(StandardScaler(), model)
        logger.info(f"Pipeline Steps: {pipeline}")
        metric = (
            balanced_accuracy_score
            if "Classifier" in self.model_name
            else self._pearsonr_corr
        )
        return pipeline, metric

    def _get_score(
        self,
        X: np.ndarray,
        y: np.ndarray,
        groups: np.ndarray | None = None,
    ) -> np.ndarray:

        if self.shuffle_target:
            np.random.shuffle(y)

        X = X.reshape(X.shape[0], -1, X.shape[-1])  # (n_samples, n_channels, n_timesteps)

        if groups is None:
            X_train, X_test, y_train, y_test = train_test_split(
                X,
                y,
                test_size=self.test_size,
                random_state=self.random_state,
                stratify=y if "Classifier" in self.model_name else None,
            )
        else:
            if self.test_size is not None:
                logger.info(f"Splitting by groups={self.group}...")
                X_train, X_test, y_train, y_test, groups_train, groups_test = (
                    train_test_split_by_group(
                        X,
                        y,
                        groups=groups,
                        test_size=self.test_size,
                        random_state=self.random_state,
                    )
                )
            else:
                logger.info(
                    f"Using fixed split defined with query='{self.test_query}'..."
                )
                train_inds, test_inds = (groups == 0)[:, 0], (groups == 1)[:, 0]
                X_train, X_test = X[train_inds], X[test_inds]
                y_train, y_test = y[train_inds], y[test_inds]
                groups_train, groups_test = groups[train_inds], groups[test_inds]

        _, n_channels, n_times = X_train.shape
        if y_train.ndim == 1:
            if self.task == "encode":
                y_train = y_train[:, None]
            y_test = y_test[:, None]
        if self.task == "decode":
            n_features = y_test.shape[-1]
        else:
            n_features = n_channels

        model, metric = self._get_model_and_metric()
        logger.info(f"Using model={model} and metric={metric}.")
        logger.info(f"Shapes: X_train={X_train.shape}, y_train={y_train.shape}")
        logger.info(f"Shapes: X_test={X_test.shape}, y_test={y_test.shape}")
        if groups is not None:
            logger.info(
                f"Shapes: groups_train={groups_train.shape}, groups_test={groups_test.shape}"
            )

        scores = np.zeros((n_times, n_features))
        times = range(n_times)
        if len(times) > 1:
            times = tqdm.tqdm(  # type: ignore
                times, desc=self.task.capitalize().replace("code", "coding...")
            )
        logger.info(f"Running pipeline on {n_times} timesteps...")
        for t in times:
            if self.task == "decode":
                model.fit(X_train[:, :, t], y_train)
                y_pred = model.predict(X_test[:, :, t])
                if y_pred.ndim == 1:
                    y_pred = y_pred[:, None]

                for d in range(n_features):
                    scores[t, d] = metric(y_test[:, d], y_pred[:, d])
            else:
                model.fit(y_train, X_train[:, :, t])
                X_pred = model.predict(y_test)
                if groups is not None:
                    raise NotImplementedError()
                for d in range(n_features):
                    scores[t, d] = metric(X_test[:, d, t], X_pred[:, d])

        return scores

    def run(self) -> np.ndarray:
        """Decode/encode the target feature from/to the neuro data using a simple linear model.
        Returns
        -------
        np.ndarray
            Scores, of shape (n_subjects, n_times, n_features).
        """
        self.prepare()
        subjects = self._get_subjects()
        scores = list(self._run_on_subject(subjects))  # type: ignore
        return np.stack(scores)

    def plot_decoding(self):
        # average over subjects and features
        scores = self.run().mean(axis=0).mean(axis=-1)
        t = np.linspace(self.start, self.start + self.duration, len(scores))
        fig = plt.figure(figsize=(8, 5))

        plt.plot(t, scores)
        plt.axvline(0, color="black", linestyle="--")
        plt.axhline(0, color="black", linestyle="--")
        plt.xlabel("Time (s)")
        plt.ylabel(
            "Balanced accuracy (%)"
            if "Classifier" in self.model_name
            else "Pearson correlation"
        )

        return fig
