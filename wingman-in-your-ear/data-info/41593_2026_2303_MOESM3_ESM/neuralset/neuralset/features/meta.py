# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp

import pandas as pd
import pydantic
import torch

from .audio import *  # noqa
from .base import *  # noqa
from .base import BaseFeature, BaseStatic
from .neuro import *  # noqa
from .text import *  # noqa
from .video import *  # type: ignore

FeatureConfig = BaseFeature
FeatureConfig = tp.Annotated[  # type: ignore
    tp.Union[
        tuple(x for x in BaseFeature._CLASSES.values())
    ],  # if "name" in x.model_fields)],
    pydantic.Field(discriminator="name"),  # serves for pydantic
]


class TimeAggregatedFeature(BaseStatic):
    """Remove the time dimension of a dynamic feature, either by summing/averaging or by
    selecting the first, middle or last time point.

    NOTE: This is not exactly a static feature because its output depends on the start and duration
    of the window (whereas static features only depend on the event). Hence, the get_static method
    is not implemented.

    Parameters
    ----------
    time_aggregation: str
        How to aggregate the time dimension.
        Can be "sum", "average", "first", "middle", "last".
    feature: FeatureConfig | BaseFeature
        The feature to aggregate.
    """

    name: tp.Literal["TimeAggregatedFeature"] = "TimeAggregatedFeature"
    time_aggregation: tp.Literal["sum", "average", "first", "last"] = "average"
    event_types: str | tp.Tuple[str, ...] = "Event"
    feature: FeatureConfig | BaseFeature

    def model_post_init(self, log__: tp.Any) -> None:
        self.event_types = self.feature.event_types
        if self.frequency != 0:
            name = self.__class__.__name__
            raise ValueError(f"{name}.frequency must be 0")
        return super().model_post_init(log__)

    def prepare(self, events: pd.DataFrame) -> None:
        self.feature.prepare(events)

    def __call__(
        self,
        events: tp.Any,  # too complex: pd.DataFrame | list | dict | ns.events.Event,
        start: float,
        duration: float,
        trigger: float | dict[str, tp.Any] | None = None,
    ) -> torch.Tensor:
        out = self.feature(events, start, duration, trigger)
        match self.time_aggregation:
            case "sum":
                return out.sum(-1)
            case "average":
                return out.mean(-1)
            case "first":
                return out[..., 0]
            case "last":
                return out[..., -1]

    def get_static(self, *args: tp.Any, **kwargs: tp.Any) -> torch.Tensor:
        raise RuntimeError(
            f"{self.name}.get_static should not be called as the feature is dynamic"
        )


class AggregatedFeature(BaseFeature):
    """Aggregate multiple features along the specified dimension.
    Note that self.feature_aggregation determines how the features are aggregated for a given event,
    whereas self.aggregation determines how different events are aggregated
    (after the features have been aggregated).
    """

    name: tp.Literal["AggregatedFeature"] = "AggregatedFeature"
    event_types: str | tp.Tuple[str, ...] = "Event"
    features: tp.List[FeatureConfig | BaseStatic]
    feature_aggregation: tp.Literal["cat", "stack", "average", "sum"] = "cat"
    frequency: tp.Literal["native"] = "native"  # defered to sub-features

    def model_post_init(self, log__: tp.Any) -> None:
        """Check that features are all static or all dynamic."""
        fts = self.features
        static_count = sum(isinstance(f, BaseStatic) for f in fts)
        if static_count not in [0, len(fts)]:
            raise ValueError("Features must be either all static or all dynamic.")
        if not static_count:  # dynamic
            frequencies = set(f.frequency for f in self.features)
            if len(frequencies) > 1:
                raise ValueError("All features must have the same frequency.")
        all_event_types = set(c for f in fts for c in f._event_types_helper.classes)
        self.event_types = tuple(c.__name__ for c in all_event_types)
        super().model_post_init(log__)

    def prepare(self, events: pd.DataFrame) -> None:
        for feature in self.features:
            feature.prepare(events)

    def __call__(self, *args: tp.Any, **kwargs: tp.Any) -> torch.Tensor:
        out = [feat(*args, **kwargs) for feat in self.features]
        aggreg = self.feature_aggregation
        if aggreg == "sum":
            return sum(out)  # type: ignore
        if aggreg == "average":
            return sum(out) / len(out)  # type: ignore
        return getattr(torch, aggreg)(out, dim=0)  # type: ignore
