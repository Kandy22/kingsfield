# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
import warnings

import pydantic

from ..utils import all_subclasses
from .base import BaseLossConfig
from .losses import ClipLoss, MultiLoss, SigLipLoss

LossConfig = BaseLossConfig  # so that MetricConfig is defined for mypy


def update_config_loss() -> None:
    global LossConfig  # pylint: disable=global-statement
    from .base import BaseLossConfig

    LossConfig = tp.Annotated[  # type: ignore
        tp.Union[tuple(all_subclasses(BaseLossConfig))],  # if "name" in x.model_fields)],
        pydantic.Field(discriminator="name"),  # serves for pydantic
    ]


update_config_loss()


class MultiLossConfig(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")
    losses: list[LossConfig]  # type: ignore
    weights: list[float] | None = None

    def build(self):
        losses = {loss.name: loss.build() for loss in self.losses}
        return MultiLoss(losses, self.weights)


update_config_loss()
