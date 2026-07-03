# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.


import logging
import typing as tp

import torch
from pydantic import Field
from torch import nn

from .base import BaseModelConfig
from .common import TemporalDownsamplingConfig
from .simpleconv import SimpleConvConfig
from .simplerconv import SimplerConvConfig
from .transformer import TransformerEncoderConfig

logger = logging.getLogger(__name__)


class ConvTransformerConfig(BaseModelConfig):
    name: tp.Literal["ConvTransformer"] = "ConvTransformer"

    dim: int = 512
    encoder_config: SimplerConvConfig | SimpleConvConfig = Field(discriminator="name")
    temporal_downsampling_config: TemporalDownsamplingConfig | None = None
    conv_pos_emb_kernel_size: int | None = (
        None  # Stride for custom positional embedding scheme of Wav2vec2.0
    )
    add_cls_token: bool = False
    transformer_config: TransformerEncoderConfig | None
    output_avg_pool: bool = (
        False  # If True, average the tokens outputted by the transformer
    )
    output_layer_dim: int | None = 0
    # Set to 0 for no output layer, or None to use the same dimension as the transformer.
    # Of note, both Bendr and Wav2vec2.0 use an output linear projection though it's not mentioned
    # in the papers.

    def build(self, n_in_channels: int, n_outputs: int | None = None) -> nn.Module:
        return ConvTransformer(
            n_in_channels,
            n_outputs or self.dim,
            config=self,
        )


class ConvTransformer(nn.Module):
    """Convolutional encoder followed by optional temporal aggregation and a transformer."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        config: ConvTransformerConfig,
    ):
        super().__init__()

        # Encoder
        self.dim = out_channels
        self.encoder = config.encoder_config.build(in_channels, self.dim)

        # Temporal downsampling
        self.temporal_downsampling = None
        if config.temporal_downsampling_config is not None:
            self.temporal_downsampling = config.temporal_downsampling_config.build(
                self.dim
            )

        # Transformer
        self.transformer = None
        if config.transformer_config is not None:
            self.transformer = config.transformer_config.build(dim=self.dim)

            # [CLS] token
            self.cls_token = None
            if config.add_cls_token:
                self.cls_token = nn.Parameter(
                    torch.empty(
                        (
                            1,
                            1,
                            self.dim,
                        )
                    ),
                    requires_grad=True,
                )
                nn.init.normal_(self.cls_token, mean=0.0, std=1.0)

            # Postional embedding
            # See https://github.com/facebookresearch/fairseq2/blob/main/src/fairseq2/models/wav2vec2/position_encoder.py
            # See https://github.com/SPOClab-ca/BENDR/blob/main/dn3_ext.py#L522
            self.rel_pos_emb = None
            if config.conv_pos_emb_kernel_size is not None:
                kernel_size = config.conv_pos_emb_kernel_size
                conv = nn.Conv1d(
                    self.dim,
                    self.dim,
                    kernel_size,
                    padding="same",
                    groups=16,  # XXX Parametrize
                )
                nn.init.normal_(
                    conv.weight, mean=0.0, std=(4.0 / (kernel_size * self.dim)) ** 0.5
                )
                nn.init.constant_(conv.bias, 0.0)  # type: ignore
                conv = nn.utils.weight_norm(
                    conv, dim=2
                )  # XXX Will be deprecated in favour of parametrizations, but not yet compatible
                # conv = nn.utils.parametrizations.weight_norm(conv, dim=2)
                self.rel_pos_emb = nn.Sequential(conv, nn.GELU())

        # Output layer
        self.output_avg_pool = config.output_avg_pool
        self.output_layer = None
        if config.output_layer_dim != 0:
            self.output_layer = nn.Linear(
                self.dim,
                config.output_layer_dim or self.dim,
            )

    def forward(  # type: ignore
        self,
        x: torch.Tensor,
        subject_ids: torch.Tensor | None = None,
        channel_positions: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        z = self.encoder.forward(
            x, subject_ids=subject_ids, channel_positions=channel_positions
        )
        z = z.transpose(2, 1)  # (B, F, T) -> (B, T, F)
        if self.temporal_downsampling is not None:
            z = self.temporal_downsampling(z.unsqueeze(dim=1)).squeeze(dim=1)

        if self.transformer is None:
            c_out = z
        else:
            c_in = z
            if self.rel_pos_emb is not None:
                pos_emb = self.rel_pos_emb(z.transpose(2, 1)).transpose(2, 1)
                c_in = c_in + pos_emb
            if self.cls_token is not None:
                c_in = torch.cat(
                    [
                        self.cls_token.repeat((c_in.shape[0], 1, 1)),
                        c_in,
                    ],
                    dim=1,
                )
            c_out = self.transformer(c_in)

        if self.output_avg_pool:
            assert c_out.ndim == 3
            c_out = c_out.mean(dim=1)

        if self.output_layer is not None:
            c_out = self.output_layer(c_out)

        return {
            "z": z,
            "c_out": c_out,
        }
