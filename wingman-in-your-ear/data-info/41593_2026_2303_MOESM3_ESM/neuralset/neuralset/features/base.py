# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing as tp
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pydantic
import torch

import neuralset as ns
from neuralset.base import Frequency as Frequency
from neuralset.base import TimedArray as TimedArray
from neuralset.base import _Module
from neuralset.events import Event, EventTypesHelper
from neuralset.segments import Segment

T = tp.TypeVar("T", bound=torch.Tensor | np.ndarray)
logger = logging.getLogger(__name__)


class BaseFeature(_Module):
    """Base class for defining features value based on a name.
    The aggregation parameter defines how to merge the values of multiple events.
    """

    event_types: str | tuple[str, ...] = ""
    # eg: event_types: str | tuple[str] = ("Image", "Text")

    aggregation: tp.Literal[
        "single", "sum", "average", "first", "middle", "last", "cat", "stack", "trigger"
    ] = "single"
    # builds feature even when no corresponding event is provided
    allow_missing: bool = False
    frequency: float | tp.Literal["native"] = 0.0
    _effective_frequency: float | None = None
    _CLASSES: tp.ClassVar[dict[str, tp.Type["BaseFeature"]]] = {}
    _event_types_helper: EventTypesHelper

    # internal
    _missing_default: torch.Tensor | None = None

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: tp.Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        # check params
        super().__init_subclass__()
        # add event requirements to the feature requirements
        if not cls._can_be_instanciated():
            return
        model_fields: dict[str, pydantic.FieldInfo] = cls.model_fields  # type: ignore
        event_types: tp.Any = model_fields["event_types"].default  # type:ignore
        name = cls.__name__
        if not event_types:
            msg = f"Default event_types must be specified for {cls.__name__}"
            raise RuntimeError(msg)
        if hasattr(cls, "event_type") or "event_type" in model_fields:
            msg = f"In {name!r}, event_type is deprecated, use event_types instead "
            msg += "as a feature name of tuple of feature names."
            raise RuntimeError(msg)
        # security checks for new _get_data
        legafuncs = [
            "_get_latents",
            "_get_latent",
            "_get_preprocessed_data",
            "_events_to_data",
            "_get_channel_positions",
        ]
        for func in legafuncs:
            if hasattr(cls, func):
                msg = f'In {name!r}, found function {func!r} which should be renamed to "_get_data"'
                raise RuntimeError(msg)
        infrafield = cls.model_fields.get("infra", None)
        if infrafield is not None:
            funcname = infrafield.default._infra_method.method.__name__
            if funcname != "_get_data":
                msg = f'In {name!r}, found infra decorating {funcname!r} it should be "_get_data" by convention'
                raise RuntimeError(msg)
        # security checks for new event_types
        if not isinstance(event_types, str):
            is_tuple = isinstance(event_types, tuple)
            if not (is_tuple and all(isinstance(d, str) for d in event_types)):
                msg = f"In {name!r}, event_types attribute must be a string "
                msg += f"or tuple of string, got {event_types}"
                raise TypeError(msg)
        type_helper = EventTypesHelper(event_types)
        for etype in type_helper.classes:
            cls.requirements = cls.requirements + etype.requirements
        BaseFeature._CLASSES[cls.__name__] = cls
        if "name" not in model_fields or model_fields["name"].default != name:  # type: ignore
            # unfortunately, this field can't be added dynamically so far :(
            # https://github.com/pydantic/pydantic/issues/1937
            indication = f"name: tp.Literal[{name!r}] = {name!r}"
            msg = f"Feature {name} has incorrect/missing name field, add:\n{indication}"
            raise NotImplementedError(msg)

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        self._event_types_helper = EventTypesHelper(self.event_types)
        name = self.__class__.__name__
        if self.frequency != "native" and self.frequency < 0.0:
            msg = f"{name}.frequency is neither 'native' nor >= 0 (got {self.frequency})."
            raise ValueError(msg)
        if not (self.frequency or isinstance(self, BaseStatic)):
            msg = f"{name}.frequency=0 is only allowed for static features (did you mean 'native'?)"
            raise ValueError(msg)

    def _exclude_from_cache_uid(self) -> list[str]:
        # feature convention from inheriting cache uid exclusion list
        return ["aggregation", "allow_missing"]

    def prepare(
        self, obj: pd.DataFrame | tp.Sequence[Event] | tp.Sequence[Segment]
    ) -> None:
        """Run _get_data on all events to cache results,
        then call the feature on a single event to populate the shape.

        Parameter
        ---------
        obj: DataFrame or list of events/segments
            The structure containing all the events, be it as a dataframe or list of events or list
            of segments. If you are calling prepare on several objects, then consider avoiding
            DataFrame as this will require more computation.
        """
        from neuralset import helpers

        events = helpers.extract_events(obj, types=self._event_types_helper)
        if self.frequency == "native" and events and hasattr(events[0], "frequency"):
            freqs = set(e.frequency for e in events)  # type: ignore
            cls = self.__class__.__name__
            if len(freqs) > 1:
                msg = f"frequency='native' in {cls} with several different frequencies: {freqs}"
                msg += "\n(all data will not be processing at the same frequency, "
                msg += "should you set the feature frequency?"
                logger.warning(msg)
            elif len(freqs) == 1:
                cls = self.__class__.__name__
                freq = list(freqs)[0]
                msg = f"Processing to native frequency in {cls}.prepare: {freq}Hz"
                logger.info(msg)
        self._get_data(events)
        if events:  # run feature on 1 event to populate shape
            self(
                events[0],
                start=events[0].start,
                duration=0.001,
                trigger=events[0].to_dict(),
            )

    def _get_data(self, events: list[Event]) -> tp.Iterable[tp.Any]:
        """Put heavy computation steps here, and cache the result using exca.MapInfra"""
        for _ in events:
            yield None

    def _get_timed_arrays(
        self, events: list[Event], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        raise NotImplementedError

    def __call__(
        self,
        events: tp.Any,  # too complex: pd.DataFrame | list | dict | ns.events.Event,
        start: float,
        duration: float,
        trigger: float | dict[str, tp.Any] | None = None,
    ) -> torch.Tensor:
        """events: the single event (dict | ns.events.Event) or the series
        of events (list of Events | pd.DataFrame) describing the events, each
        containing start and duration.
        start: the start of the segment in the same timeline as the event.
        duration: the duration of the segment.
        """
        _input_events = events

        from neuralset import helpers

        # Check argument
        assert duration >= 0.0, f"{duration} must be >= 0."
        event_types = self._event_types_helper.classes
        name = self.__class__.__name__
        if self.aggregation == "trigger":
            type_ = trigger.get("type", None) if isinstance(trigger, dict) else trigger
            t: tp.Any = trigger
            if type_ in Event._CLASSES:  # convert to event if possible
                t = Event.from_dict(trigger)
            if not isinstance(t, event_types):  # clear error message
                aggregation = self.aggregation
                msg = f"Feature {name} has {aggregation=} but trigger is {t!r} (not {event_types})"
                raise ValueError(msg)
            events = [t]
        events = helpers.extract_events(events, types=self._event_types_helper)
        # create an empty event if nothing is available
        if not events and self.allow_missing and self._missing_default is not None:
            if self._effective_frequency is None:
                msg = f"_missing_default was set for {name} but _effective_frequency is missing"
                raise RuntimeError(msg)
            default = self._missing_default
            freq = Frequency(self._effective_frequency)
            if freq:
                n_times = max(1, freq.to_ind(duration))
                reps = [1 for _ in range(default.ndim)] + [n_times]
                default = default.unsqueeze(-1).repeat(reps)
            return default

        if not events:
            found_types = {type(e) for e in _input_events}
            msg = f"No {event_types} found in segment for feature {name} "
            msg += f"(types found: {found_types} in {_input_events}) "
            if not self.allow_missing:
                msg += f"(filter invalid segments or set allow_missing=True to {name})"
            else:
                msg += "and feature shape not populated "
                msg += '(you may need to call "prepare" on the feature).'
            raise ValueError(msg)

        # Extract value for each relevant event
        if self.aggregation in ("first", "trigger", "single"):
            if self.aggregation == "single" and len(events) > 1:
                msg = f"Found {len(events)} events in the segment but expected only one "
                msg += f"since {name}.aggregation='single'."
                msg += "Update it to sum/average/first/trigger/... ?\n"
                msg += f"{events=}"
                raise ValueError(msg)
            events = events[:1]
        elif self.aggregation == "last":
            events = events[-1:]
        elif self.aggregation == "middle":
            events = [events[len(events) // 2]]
        tarrays = list(
            self._get_timed_arrays(events=events, start=start, duration=duration)
        )
        if self._effective_frequency is None:
            if self.frequency == "native":
                self._effective_frequency = tarrays[0].frequency
            else:
                self._effective_frequency = self.frequency
        # aggregate arrays
        time_info: dict[str, tp.Any] = {
            "start": start,
            "frequency": self._effective_frequency,
            "duration": duration,
        }
        aggreg = "sum"
        if self.aggregation == "average" and len(tarrays) > 1:
            aggreg = self.aggregation
        if self.aggregation not in ("cat", "stack"):
            out = TimedArray(aggregation=aggreg, **time_info)
            for ta in tarrays:
                out += ta
        else:
            arrays = []
            for ta in tarrays:
                out = TimedArray(**time_info)
                out += ta
                arrays.append(out.data)
            func = np.concatenate if self.aggregation == "cat" else np.stack
            data = func(arrays, axis=0)
            out = TimedArray(data=data, **time_info)
        tensor = torch.from_numpy(out.data)
        if not tensor.ndim:
            tensor = tensor.unsqueeze(0)
        # record shape and return
        if self._missing_default is None:
            # last dimension is time if frequency is not 0
            shape = tuple(tensor.shape[: -1 if self.frequency else None])
            self._missing_default = torch.zeros(*shape, dtype=tensor.dtype)
        return tensor

    def _events_from_dataframe(self, events: pd.DataFrame) -> list[tp.Any]:
        # we're loosing type here :(
        from neuralset import helpers  # avoid circular imports

        warnings.warn(
            "_events_from_dataframe is deprecated, use ns.helpers.extract_events instead",
            DeprecationWarning,
        )
        events_ = helpers.extract_events(events, types=self._event_types_helper)
        return events_


class BaseDynamic(BaseFeature):
    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        msg = "BaseDynamic is deprecated, replace it with BaseFeature"
        warnings.warn(msg, DeprecationWarning)


class BaseStatic(BaseFeature):
    frequency: float = 0.0

    def get_static(self, event: ns.events.Event) -> torch.Tensor:
        """retrieve the static embedding"""
        raise NotImplementedError

    def _get_timed_arrays(
        self, events: list[Event], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        for event in events:
            embedding = self.get_static(event)
            ta = TimedArray(
                frequency=0,
                duration=event.duration,
                start=event.start,
                data=embedding.numpy(),
            )
            yield ta


class HuggingFaceMixin(pydantic.BaseModel):
    """Mixin for features that use a HuggingFace model.
    These features all return a tensor of shape (n_layers, n_tokens, *embedding_shape).
    This mixin determines how to aggregate the layers and tokens.

    Parameters
    ----------
    model_name: str
        Name of the model to use.
    device: str
        Device to use for the model:
        - cpu: for cpu computation
        - cuda: for using gpu0
        - auto: to use gpu if available else cpu
        - accelerate: to use huggingface accelerate (maps to multiple-gpus + use float16)
    layers: float | list[float] | "all"
        Specifies the layers to keep.
        - "all": keep all layers
        - a float between 0 and 1 (or list of): the relative depth of the layer(s) to use,
        where 0 stands for the first layer and 1 for the last layer.
    cache_all_layers: bool
        If True, all layers are cached (beware of disk usage!).
        If False, only cache the output of the layers specified by `layers`.
    layer_aggregation: str
        How to aggregate the layers (first dimension of the tensor of activations).
        Can be "mean", "sum", "group_mean" or None (in which case we keep the original dimension).
        "group_mean" will average the layers by groups defined by the layers parameter,
        e.g. if layers=[0, 0.5, 1] and there are 10 layers, the layers will be grouped as [0:5], [5:10].
    token_aggregation: str
        How to aggregate the tokens (second dimension of the tensor of activations).
        Can be "first", "last", "mean", "sum", "max", or None (in which case we keep the original dimension).
    """

    requirements: tp.ClassVar[tp.Tuple[str, ...]] = (
        "transformers>=4.29.2",
        "huggingface_hub>=0.27.0",
    )
    model_name: str
    device: tp.Literal["auto", "cpu", "cuda", "accelerate"] = "auto"
    layers: float | list[float] | tp.Literal["all"] = 2 / 3
    cache_all_layers: bool = False
    layer_aggregation: tp.Literal["mean", "sum", "group_mean"] | None = "mean"
    token_aggregation: tp.Literal["first", "last", "mean", "sum", "max"] | None = "mean"
    _REPOS: tp.ClassVar[list[str]] = []
    _skip_repo_check: bool = False  # for simpler hacking (eg: custom dinov2 checkpoints)

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.layers != "all":
            layers = self.layers if isinstance(self.layers, list) else [self.layers]
            if not all(isinstance(layer, float) and 0 <= layer <= 1 for layer in layers):
                raise ValueError("The layers must be floats between 0 and 1")
        if not self._skip_repo_check and not self.repo_exists():
            raise ValueError(f"The model {self.model_name} does not exist")

    def repo_exists(self) -> bool:
        fp = Path(__file__).with_name("data") / "huggingface-repos.txt"
        name = self.model_name
        if not self._REPOS:  # load offline huggingface white list
            if not fp.exists():
                raise RuntimeError(f"Please reinstall neuralset: missing file {fp}")
            self._REPOS.extend(fp.read_text().splitlines())
        if name in self._REPOS:
            return True
        else:
            from huggingface_hub import repo_info

            try:  # if not in whitelist, check through API and save it if it exists
                repo_info(name)
                self._REPOS.append(name)
                self._REPOS.sort()
                try:
                    fp.write_text("\n".join(self._REPOS))
                except Exception:
                    pass  # nevermind if there is no write permission
                return True
            except Exception:
                return False

    @classmethod
    def _exclude_from_cls_uid(cls) -> tp.List[str]:
        return ["device"]

    def _exclude_from_cache_uid(self) -> tp.List[str]:
        excluded = ["device"]
        if self.cache_all_layers:
            excluded.extend(["layers", "layer_aggregation"])
        return excluded

    def _aggregate_layers(self, latents: np.ndarray) -> np.ndarray:
        """
        Input:
            a tensor of activations of shape (n_model_layers, *embedding_shape)
        Output:
            a tensor of activations of following shape:
            - (len(self.layers), *embedding_shape) if layer_aggregation is None,
            - (len(self.layers)-1, *embedding_shape) if layer_aggregation is "group_mean",
            - (*embedding_shape) if layer_aggregation is "mean" or "sum".
        This function should be called before caching to reduce the size of the cached tensors,
        except if cache_all_layers is True, in which case it should be called after caching.
        """
        n_model_layers = latents.shape[0]
        if self.layers == "all":
            layer_indices = list(range(n_model_layers))
        else:
            layers = self.layers if isinstance(self.layers, list) else [self.layers]
            layer_indices = np.unique([int(i * (n_model_layers - 1)) for i in layers]).tolist()  # type: ignore
        if len(layer_indices) == 1:
            if self.layer_aggregation is None:
                return latents[layer_indices[0]][None, :]
            else:
                return latents[layer_indices[0]]
        else:  # aggregate
            if self.layer_aggregation == "mean":
                return latents[layer_indices].mean(0)  # type: ignore
            elif self.layer_aggregation == "sum":
                return latents[layer_indices].sum(0)  # type: ignore
            elif self.layer_aggregation == "group_mean":
                groups = []
                layer_indices[-1] += 1
                for l1, l2 in zip(layer_indices[:-1], layer_indices[1:]):
                    groups.append(latents[l1:l2].mean(0))
                return np.stack(groups)
            elif self.layer_aggregation is None:
                return latents[layer_indices]
            else:
                raise ValueError(f"Unknown layer aggregation: {self.layer_aggregation}")

    def _aggregate_tokens(self, latents: T) -> T:
        """
        Input:
            a tensor of activations of shape (layer_idx, token_idx, *embedding_shape)
        Output:
            a tensor of activations of same shape if token_aggregation is None
            else (layer_idx, *embedding_shape).
        This function should always be called before caching, to reduce the size
        of the cached tensors.
        """
        match self.token_aggregation:
            case "mean":
                out = latents.mean(axis=1)  # type: ignore
            case "sum":
                out = latents.sum(axis=1)  # type: ignore
            case "max":
                out = latents.max(axis=1)  # type: ignore
                if isinstance(latents, torch.Tensor):
                    out = out.values
            case "first":
                # np.take in numpy, torch.select in torch
                out = latents[:, 0, ...]
            case "last":
                out = latents[:, -1, ...]
            case None:
                out = latents
        return out  # type: ignore


class EventDetector(BaseFeature):
    """Feature that detects keystroke events at each time point.
    Returns a binary tensor indicating whether there is a keystroke event at each time point.
    """

    name: tp.Literal["EventDetector"] = "EventDetector"
    event_types: str = "Event"
    frequency: float = 100.0
    mode: tp.Literal[
        "start",
        "duration_middle",
        "duration_label",
        "duration_label_full",
        "middle",
        "smooth",
        "super_smooth",
        "super_smooth_constant",
        "super_smooth_constant_start",
        "super_smooth_constant_end",
        "super_smooth_just_one",
        "flat_confidence",
        "raw_duration",
        "start_DETR",
        "end_DETR",
        "center_DETR",
        "duration_DETR",
        "class_DETR",
        "multiclass_DETR",
        "middle_presence",
        "class_label_full",
        "reaction_time_gaussian",
    ] = "start"
    smooth_window: float | None = None
    reaction_sigma_s: float = 0.05
    reaction_offset_s: float = 0.0
    smoothing_type: tp.Literal["gaussian", "triangular"] | None = None
    allow_missing: bool = True
    handle_05: str | None = None
    variable_sigma: bool = False
    # multiply_labels: float = 1.0
    alpha: float | None = None
    mapping: dict[str, int] | None = None
    super_smooth_center: str | None = None
    max_events: int | None = None  #
    _max_duration: float | None = None

    def prepare(self, events: pd.DataFrame) -> None:
        from neuralset import helpers

        if "_DETR" in self.mode:
            events_of_interest = events[events.type == self.event_types]
            self._max_duration = (
                events_of_interest.duration.max() * self.frequency
            )  # We want the max duration in samples

        events_ = helpers.extract_events(events, types=self._event_types_helper)
        if events_:
            self(
                events_[0],
                start=events_[0].start,
                duration=15,
                trigger=events_[0].to_dict(),
            )

    def _get_timed_arrays(self, events, start, duration):
        # Calculate number of samples based on frequency and duration
        n_samples = int(duration * self.frequency)
        # Create output array initialized to zeros
        data = np.zeros((1, n_samples), dtype=np.float32)

        if self.mode in {
            "center_DETR",
            "start_DETR",
            "end_DETR",
            "duration_DETR",
            "class_DETR",
            "multiclass_DETR",
        }:

            selected_events = [
                e
                for e in events
                if start <= e.start and (e.start + e.duration) <= start + duration
            ]

            # Compute the attribute values according to the mode
            if self.mode == "center_DETR":
                values = [
                    (e.start + e.duration / 2 - start) / duration for e in selected_events
                ]
            elif self.mode == "start_DETR":
                values = [(e.start - start) / duration for e in selected_events]
            elif self.mode == "end_DETR":
                values = [
                    (e.start + e.duration - start) / duration for e in selected_events
                ]
            elif self.mode == "duration_DETR":
                values = [e.duration / duration for e in selected_events]
            elif self.mode == "class_DETR":
                values = [1.0 for _ in selected_events]
            elif self.mode == "multiclass_DETR":
                if self.event_types == "Button":
                    values = [int(self.mapping[e.button]) for e in selected_events]
                elif self.event_types == "Stimulus":
                    values = [int(self.mapping[e.description]) for e in selected_events]
                elif self.event_types in ["Seizure", "Artifact"]:
                    values = [int(self.mapping[e.state]) for e in selected_events]
                elif self.event_types in ["ButtonEmg"]:
                    values = [int(self.mapping[e.text]) for e in selected_events]
                elif self.event_types in ["ButtonC"]:
                    values = [int(self.mapping[e.extra["text"]]) for e in selected_events]
                elif self.event_types in ["Phoneme"]:
                    if len(self.mapping) > 2:
                        values = [
                            int(self.mapping[e.extra["phoneme"]]) for e in selected_events
                        ]
                    else:
                        values = [
                            int(self.mapping[e.extra["speech"]]) for e in selected_events
                        ]
                elif self.event_types in ["Word"]:
                    if len(self.mapping) > 2:
                        values = [
                            int(self.mapping[e.extra["word_type"]])
                            for e in selected_events
                        ]
                    else:
                        values = [
                            int(self.mapping[e.extra["speech"]]) for e in selected_events
                        ]
            else:
                raise ValueError(f"Unsupported mode: {self.mode}")

            # Pad or truncate to max_events
            values = values[: self.max_events]
            pad_width = self.max_events - len(values)
            if pad_width > 0:
                values = np.pad(values, (0, pad_width), constant_values=0.0)

            # Embed into channel axis, t=0
            data = np.zeros((self.max_events, n_samples), dtype=np.float32)
            data[:, 0] = values

            yield ns.base.TimedArray(
                data=data, start=start, duration=duration, frequency=self.frequency
            )
            return

        for event in events:
            if self.mode == "reaction_time_gaussian":
                if self.handle_05 == "clamp":
                    rt = (
                        np.maximum(event.extra["reaction_time"], 0.5) - 0.5
                    )  # To handle RT < 0.5
                else:
                    rt = event.extra["reaction_time"] - 0.5

                rt = rt + self.reaction_offset_s

                if self.handle_05 == "uniform" and rt <= 0:
                    uniform_window = np.ones(n_samples) / n_samples
                    data[0, :] = np.maximum(data[0, :], uniform_window)
                    continue

                rt_idx = int(rt * self.frequency)
                if 0 <= rt_idx < n_samples:
                    sigma_samples = self.reaction_sigma_s * self.frequency
                    half_window = int(3 * sigma_samples)
                    if self.variable_sigma:
                        samples_to_edge = min(rt_idx, n_samples - rt_idx)
                        half_window = min(half_window, samples_to_edge)
                    start_idx = max(0, rt_idx - half_window)
                    end_idx = min(n_samples, rt_idx + half_window)

                    if end_idx > start_idx:
                        time_vector = np.arange(start_idx, end_idx)
                        gaussian_window = np.exp(
                            -0.5 * ((time_vector - rt_idx) ** 2) / (sigma_samples**2)
                        )
                        gaussian_window = gaussian_window / gaussian_window.sum()
                        data[0, start_idx:end_idx] = np.maximum(
                            data[0, start_idx:end_idx], gaussian_window
                        )
            else:
                event_start_idx = int((event.start - start) * self.frequency)
                event_end_idx = int(
                    (event.start + event.duration - start) * self.frequency
                )
                event_center = event.start + event.duration / 2
                if not (start <= event_center < start + duration):
                    continue

                if self.mode == "start":
                    if 0 <= event_start_idx < n_samples:
                        data[0, event_start_idx] = 1

                elif self.mode == "middle":
                    middle_idx = int((event_start_idx + event_end_idx) / 2)
                    if 0 <= middle_idx < n_samples:
                        data[0, middle_idx] = 1

                elif self.mode == "duration_middle":
                    middle_idx = int((event_start_idx + event_end_idx) / 2)
                    if 0 <= middle_idx < n_samples:
                        data[0, middle_idx] = event.duration / duration

                elif self.mode == "duration_label":
                    middle_idx = int((event_start_idx + event_end_idx) / 2)
                    dur = event_end_idx - event_start_idx
                    if 0 <= middle_idx < n_samples:
                        data[0, middle_idx] = dur / self._max_duration

                elif self.mode == "raw_duration":
                    middle_idx = int((event_start_idx + event_end_idx) / 2)
                    dur = event_end_idx - event_start_idx
                    if 0 <= middle_idx < n_samples:
                        data[0, middle_idx] = dur

                elif self.mode == "duration_label_full":
                    middle_idx = (
                        event_start_idx + event_end_idx
                    ) // 2  # Use integer division
                    dur = event_end_idx - event_start_idx
                    # Ensure indices are within the valid range
                    if 0 <= event_start_idx < event_end_idx <= n_samples:
                        data[0, event_start_idx:event_end_idx] = dur / self._max_duration

                elif self.mode == "smooth":
                    center_idx = int((event_start_idx + event_end_idx) / 2)
                    half_window_samples = int(self.smooth_window * self.frequency / 2)
                    start_idx = max(0, center_idx - half_window_samples)
                    end_idx = min(n_samples, center_idx + half_window_samples)

                    if end_idx <= start_idx:
                        continue  # avoid zero-size slices

                    window_len = end_idx - start_idx

                    if self.smoothing_type == "gaussian":
                        sigma = half_window_samples / 2
                        window = np.exp(
                            -0.5
                            * ((np.arange(window_len) - window_len // 2) / sigma) ** 2
                        )
                    elif self.smoothing_type == "triangular":
                        window = 1 - np.abs(np.arange(window_len) - window_len // 2) / (
                            window_len // 2 + 1
                        )

                    else:
                        raise ValueError("Unsupported smoothing type")

                    window = window / window.max()  # Normalize to peak = 1
                    data[0, start_idx:end_idx] = np.maximum(
                        data[0, start_idx:end_idx], window
                    )  # In case of overlap, keep the maximum value

                elif self.mode == "super_smooth":
                    if self.super_smooth_center == "center":
                        center_idx = int((event_start_idx + event_end_idx) / 2)
                    elif self.super_smooth_center == "start":
                        center_idx = event_start_idx
                    elif self.super_smooth_center == "end":
                        center_idx = event_end_idx

                    # Sharp localization
                    """
                    Button: event is ~12 samples (0.1s * 125 Hz), Gaussian spans ~6 samples → covers ~50% of event duration, but since it's just the start/end it’s fine.
                    Sentence: event is ~750 samples, Gaussian spans ~16 samples → ~2% of the event duration, enough to localize without covering the full event.
                    """
                    if self.event_types == "Button":
                        sigma = 3
                    elif self.event_types == "Word":
                        sigma = 5
                    elif self.event_types == "Phoneme":
                        sigma = 2
                    elif self.event_types == "Sentence":
                        sigma = 8
                    else:
                        raise ValueError(
                            f"Unsupported event type {self.event_types} for super_smooth_start mode."
                        )

                    half_window = int(3 * sigma)
                    start_idx_window = max(0, center_idx - half_window)
                    end_idx_window = min(n_samples, center_idx + half_window)

                    if end_idx_window <= start_idx_window:
                        continue

                    time_vector = np.arange(start_idx_window, end_idx_window)
                    gaussian_window = np.exp(
                        -0.5 * ((time_vector - center_idx) ** 2) / (sigma**2)
                    )
                    data[0, start_idx_window:end_idx_window] = np.maximum(
                        data[0, start_idx_window:end_idx_window], gaussian_window
                    )

                elif self.mode == "super_smooth_constant":
                    center_idx = int((event_start_idx + event_end_idx) / 2)

                    if self.event_types == "Button":
                        sigma = (
                            self.frequency * 0.03
                        )  # 30ms roughly 1/3 of an event duration
                    elif self.event_types == "Word":
                        sigma = (
                            self.frequency * 0.1
                        )  # 100ms roughly 1/3 of an event duration
                    elif self.event_types == "Phoneme":
                        sigma = (
                            self.frequency * 0.025
                        )  # 25ms roughly 1/3 of an event duration
                    elif self.event_types == "Sentence":
                        sigma = self.frequency * 2  # 2s roughly 1/3 of an event duration
                    else:
                        raise ValueError(
                            f"Unsupported event type {self.event_types} for super_smooth_constant mode."
                        )

                    half_window = int(3 * sigma)
                    start_idx = max(0, center_idx - half_window)
                    end_idx = min(n_samples, center_idx + half_window)

                    if end_idx <= start_idx:
                        continue

                    time_vector = np.arange(start_idx, end_idx)
                    gaussian_window = np.exp(
                        -0.5 * ((time_vector - center_idx) ** 2) / (sigma**2)
                    )
                    data[0, start_idx:end_idx] = np.maximum(
                        data[0, start_idx:end_idx], gaussian_window
                    )

                elif self.mode == "class_label_full":
                    # Get integer label from mapping depending on event type
                    if self.event_types == "Button":
                        label_val = int(self.mapping[event.button])
                    elif self.event_types in ["FakeStimulus", "Stimulus"]:
                        label_val = int(self.mapping[event.description])
                    elif self.event_types in [
                        "FakeSeizure",
                        "Seizure",
                        "FakeArtifact",
                        "Artifact",
                    ]:
                        label_val = int(self.mapping[event.state])
                    elif self.event_types in ["FakePhoneme", "Phoneme"]:
                        if len(self.mapping) > 2:
                            label_val = int(self.mapping[event.extra["phoneme"]])
                        else:
                            label_val = int(self.mapping[event.extra["speech"]])
                    elif self.event_types in ["FakeWord", "Word"]:
                        if len(self.mapping) > 2:
                            label_val = int(self.mapping[event.extra["word_type"]])
                        else:
                            label_val = int(self.mapping[event.extra["speech"]])
                    else:
                        raise ValueError(
                            f"Unsupported event type {self.event_types} for class_label_full mode."
                        )

                    # Fill the entire event duration with the class ID
                    start_idx = max(0, event_start_idx)
                    end_idx = min(n_samples, event_end_idx)

                    if end_idx > start_idx:
                        data[0, start_idx:end_idx] = label_val

                elif self.mode == "super_smooth_just_one":
                    center_idx = int((event_start_idx + event_end_idx) / 2)
                    if 0 <= center_idx < n_samples:
                        data[0, center_idx] = 1.0

                elif self.mode == "flat_confidence":
                    start_idx = max(0, event_start_idx)
                    end_idx = min(n_samples, event_end_idx)

                    if end_idx > start_idx:
                        data[0, start_idx:end_idx] = 1.0

        yield ns.base.TimedArray(
            data=data, start=start, duration=duration, frequency=self.frequency
        )


class Pulse(BaseStatic):
    event_types: str | tuple[str, ...] = "Event"
    name: tp.Literal["Pulse"] = "Pulse"

    def get_static(self, event: ns.events.Event) -> torch.Tensor:
        return torch.ones(1, dtype=torch.float32)


class Stimulus(BaseStatic):
    """Static event which sets the value to `code`."""

    event_types: tp.Literal["Stimulus"] = "Stimulus"
    name: tp.Literal["Stimulus"] = "Stimulus"

    def get_static(self, event: ns.events.Stimulus) -> torch.Tensor:
        return torch.tensor(event.code).long()


class LabelEncoder(BaseStatic):
    """Encode a given field from an event, e.g. to be used as a label.

    Parameters
    ----------
    event_types :
        Type of event to apply this feature to.
    event_field :
        Field to encode from the event.
    return_one_hot :
        If True, return one-hot representation of the index. Otherwise, return an int in
        [0, n_unique_values - 1].
    predefined_mapping : Optional dict
        If provided, use this mapping from label to index instead of computing it from data.
    """

    name: tp.Literal["LabelEncoder"] = "LabelEncoder"
    event_types: str | tuple[str, ...] = "Event"
    event_field: str
    return_one_hot: bool = False
    predefined_mapping: dict[str, int] | None = None

    _label_to_ind: dict[str, int] = {}
    _n_classes: int = 0

    def _extract_event_field(self, event: ns.events.Event) -> str:
        """Get the event field value from the event."""
        if hasattr(event, self.event_field):
            return getattr(event, self.event_field)
        else:
            return event.extra[self.event_field]

    def prepare(
        self, obj: pd.DataFrame | tp.Sequence[Event] | tp.Sequence[Segment]
    ) -> None:
        from neuralset import helpers

        events = helpers.extract_events(obj, types=self._event_types_helper)
        field = self.event_field
        if not all(hasattr(e, field) or field in e.extra for e in events):
            msg = f"Field {field} not found in events for {self.__class__.__name__}"
            raise TypeError(msg)

        labels = set(self._extract_event_field(e) for e in events)
        if len(labels) < 2:
            logger.warning(
                f"LabelEncoder has only found one label: {labels}. "
                "This was probably not intended."
            )

        if self.predefined_mapping:
            assert all(
                label in self.predefined_mapping for label in labels
            ), "Some labels in the data are missing from the predefined_mapping."
            self._label_to_ind = self.predefined_mapping
        else:
            self._label_to_ind = {label: i for i, label in enumerate(sorted(labels))}

        self._n_classes = len(set(self._label_to_ind.values()))
        expected_indices = set(range(self._n_classes))
        actual_indices = set(self._label_to_ind.values())
        if expected_indices != actual_indices:
            logger.warning(
                f"Label indices are not contiguous. Expected indices: {expected_indices}, "
                f"but got: {actual_indices}. "
                "This may cause issues with one-hot encoding or class-based operations."
            )

        if events:
            self(events[0], events[0].start, duration=0.001, trigger=events[0].to_dict())

    def get_static(self, event: ns.events.Event) -> torch.Tensor:
        if not self._label_to_ind:
            msg = "Must call label_encoder.prepare(events) before using the feature."
            raise ValueError(msg)
        inds = [self._label_to_ind[self._extract_event_field(event)]]
        label = torch.tensor(inds, dtype=torch.long)
        if self.return_one_hot:
            label = torch.nn.functional.one_hot(label, num_classes=self._n_classes)
        return label
