# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing as tp
from math import prod

import torch
from torch import nn

from .base import BaseModelConfig
from .common import ChannelMergerConfig, SubjectLayersConfig

logger = logging.getLogger(__name__)


class SimplerConvConfig(BaseModelConfig):
    name: tp.Literal["SimplerConv"] = "SimplerConv"

    # Subject specific layer
    subject_layers_config: SubjectLayersConfig | None = None

    # Channel merger to allow learning on different montages
    merger_config: ChannelMergerConfig | None = None

    # Convolutional encoder
    # NOTE: Default values are inspired from BENDR/wav2vec2.0
    n_hidden_channels: int = 512
    kernel_sizes: tuple[int, ...] = (3, 2, 2, 2, 2)
    strides: tuple[int, ...] = (3, 2, 2, 2, 2)
    dropout: float = 0.0

    def build(self, n_in_channels: int, n_outputs: int | None = None) -> nn.Module:
        return SimplerConv(n_in_channels, n_outputs, config=self)


class SimplerConv(nn.Module):
    """Convolutional encoder inspired from BENDR/wav2vec2.0, with channel attention."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int | None,
        config: SimplerConvConfig | None = None,
    ):
        super().__init__()
        config = config if config is not None else SimplerConvConfig()

        assert len(config.kernel_sizes) == len(config.strides)
        self.kernel_sizes = config.kernel_sizes
        self.strides = config.strides
        self.out_channels = out_channels

        self.merger = None
        if config.merger_config is not None:
            self.merger = config.merger_config.build()
            in_channels = config.merger_config.n_virtual_channels

        self.subject_layers = None
        if config.subject_layers_config:
            self.subject_layers = config.subject_layers_config.build(
                in_channels, config.n_hidden_channels
            )
            in_channels = config.n_hidden_channels

        # Convolutional encoder
        self.encoder = nn.ModuleList()
        n_layers = len(self.kernel_sizes)
        last_out_channels = (
            config.n_hidden_channels if self.out_channels is None else self.out_channels
        )
        for i, (kernel_size, stride) in enumerate(zip(self.kernel_sizes, self.strides)):
            out_channels = (
                config.n_hidden_channels if i < n_layers - 1 else last_out_channels
            )
            self.encoder.append(
                nn.Sequential(
                    nn.Conv1d(
                        in_channels if i == 0 else config.n_hidden_channels,
                        out_channels,
                        kernel_size=kernel_size,
                        stride=stride,
                    ),
                    nn.Dropout1d(config.dropout),  # Channel dropout
                    nn.GroupNorm(
                        out_channels // 2, out_channels
                    ),  # Like in BENDR, see https://github.com/SPOClab-ca/BENDR/blob/main/dn3_ext.py#L386
                    nn.GELU(),
                )
            )

    @property
    def downsampling_factor(self) -> int:
        return prod(self.strides)

    @property
    def receptive_field(self) -> int:
        """Compute the receptive field of the encoder.
        See https://distill.pub/2019/computing-receptive-fields/, Eq. 2
        """
        cumprod_strides = [1] + torch.cumprod(
            torch.tensor(self.strides[:-1]), dim=0
        ).tolist()
        return int(
            sum((k - 1) * s for k, s in zip(self.kernel_sizes, cumprod_strides)) + 1
        )

    def forward(
        self,
        x: torch.Tensor,
        subject_ids: torch.Tensor | None = None,
        channel_positions: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if self.merger is not None:
            x = self.merger(x, subject_ids, channel_positions)

        if self.subject_layers is not None:
            x = self.subject_layers(x, subject_ids)

        for block in self.encoder:
            x = block(x)

        return x
