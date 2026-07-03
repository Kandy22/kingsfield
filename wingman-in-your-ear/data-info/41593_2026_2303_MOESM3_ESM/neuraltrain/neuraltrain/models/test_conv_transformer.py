# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import pytest
import torch

from .conv_transformer import ConvTransformer, ConvTransformerConfig
from .simpleconv import SimpleConv
from .simplerconv import SimplerConv


@pytest.fixture
def fake_eeg():
    batch_size = 16
    n_channels = 8
    n_times = 800
    meg = torch.randn(batch_size, n_channels, n_times)
    return meg


def test_conv_transformer_with_simpler_conv(fake_eeg):
    batch_size, n_in_channels, n_times = fake_eeg.shape
    channel_positions = torch.rand((batch_size, n_in_channels, 2))

    dim = 512
    model = ConvTransformerConfig(
        encoder_config=dict(
            name="SimplerConv",
            merger_config={},
            kernel_sizes=(5, 2),
            strides=(5, 2),
            dropout=0.5,
        ),
        temporal_downsampling_config=dict(
            kernel_size=2,
            stride=2,
            layer_norm=True,
            layer_norm_affine=True,
            gelu=True,
        ),
        conv_pos_emb_kernel_size=5,
        transformer_config={},
    ).build(n_in_channels=n_in_channels, n_outputs=dim)
    assert isinstance(model, ConvTransformer)
    assert isinstance(model.encoder, SimplerConv)

    out = model(fake_eeg, channel_positions=channel_positions)
    assert out.keys() == {"z", "c_out"}

    receptive_field = 20  # (5 * 2) * 2
    assert out["z"].shape == (batch_size, n_times / receptive_field, dim)
    assert out["c_out"].shape == (batch_size, n_times / receptive_field, dim)


def test_conv_transformer_with_simple_conv(fake_eeg):
    batch_size, n_in_channels, n_times = fake_eeg.shape

    dim, output_layer_dim = 512, 4
    model = ConvTransformerConfig(
        encoder_config=dict(
            name="SimpleConv",
            merger_config=None,
        ),
        temporal_downsampling_config=dict(
            kernel_size=4,
            stride=4,
        ),
        conv_pos_emb_kernel_size=5,
        add_cls_token=True,
        transformer_config={},
        output_layer_dim=output_layer_dim,
    ).build(n_in_channels=n_in_channels, n_outputs=dim)
    assert isinstance(model, ConvTransformer)
    assert isinstance(model.encoder, SimpleConv)

    out = model(fake_eeg)
    assert out.keys() == {"z", "c_out"}

    assert out["z"].shape == (batch_size, n_times / 4, dim)
    assert out["c_out"].shape == (batch_size, 1 + n_times / 4, output_layer_dim)
