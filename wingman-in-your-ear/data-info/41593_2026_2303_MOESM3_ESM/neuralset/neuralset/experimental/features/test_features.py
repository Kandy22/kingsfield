# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp
import urllib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

import neuralset as ns

# pylint: disable=unused-import
from neuralset.features.test_image import cat_event, create_image  # noqa
from neuralset.features.test_video import video_event  # noqa

from . import image as im
from . import torchhub as th

# pylint: disable=redefined-outer-name


@pytest.mark.parametrize(
    "in_shapes,out_shape",
    [
        ([(3, 32, 128, 128)], (3, 1, 32)),
        ([(3, 100, 32), (3, 100, 64)], (3, 1, 64)),
        ([(3, 100, 64), (3, 100, 32)], (3, 1, 64)),
    ],
)
def test_normalize_states(
    in_shapes: tp.List[tp.Tuple[int, ...]], out_shape: tp.Tuple[int, ...]
) -> None:
    states = [torch.rand(shape) for shape in in_shapes]
    out = im._normalize_states(states, "efficientnet")
    assert out[0].shape == out_shape


def test_normalize_states_error() -> None:
    in_shapes = [(3, 100, 64), (3, 100, 32)]
    states = [torch.rand(shape) for shape in in_shapes]
    with pytest.raises(ValueError):
        im._normalize_states(states, "blublu")  # should only work for some names


@pytest.mark.parametrize(
    "name,shape",
    [
        ("facebook/detr-resnet-50", (14, 256)),
        ("google/efficientnet-b0", (17, 320)),
        ("nvidia/mit-b0", (4, 256)),
        ("facebook/dinov2-small-imagenet1k-1-layer", (13, 384)),
        ("microsoft/swinv2-tiny-patch4-window8-256", (5, 768)),
        ("torchhub/alexnet", (6, 4096)),
        ("openai/clip-vit-base-patch32", (13, 768)),
        ("timm/resnet18.a1_in1k", (5, 512)),
        # deactivate some tests for now for faster CI / smaller CI cache:
        # ("facebook/sam-vit-base", (13, 768)),
        # ("google/vit-hybrid-base-bit-384", (13, 768)),
        # ("facebook/data2vec-vision-base", (13, 768)),
        # ("facebook/mask2former-swin-tiny-coco-instance", (7, 768)),
        # ("facebook/dpt-dinov2-base-kitti", (13, 768)),
        # ("openmmlab/upernet-convnext-tiny", (5, 768)),
        # ("microsoft/git-base", (7, 768)),
    ],
)
@pytest.mark.parametrize(
    "device", ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])
)
def test_image_layer_models(
    cat_event: ns.events.Image, name: str, shape: tp.Tuple[int, int, int], device: str
) -> None:
    feat = im.ExtendedHuggingFaceImage(
        device="cpu", model_name=name, cache_all_layers=True, token_aggregation="mean"
    )
    try:
        out = next(iter(feat._get_data([cat_event])))
    except urllib.error.HTTPError:
        pytest.skip("torchhub rate limit")
    assert out.shape == shape


def test_torchhub_in_hf_image(cat_event: ns.events.Image) -> None:
    name = np.random.choice(list(th.TorchHubModel.REGISTER))
    print(f"Testing torchhub model: {name}")
    feat = im.ExtendedHuggingFaceImage(device="cpu", model_name="torchhub/" + name)
    try:
        out = next(iter(feat._get_data([cat_event])))
    except urllib.error.HTTPError:
        pytest.skip("torchhub rate limit")
    assert out.shape[0] > 2


def test_timm_image(cat_event: ns.events.Image) -> None:
    name = "timm/resnet18.a1_in1k"
    feat = im.ExtendedHuggingFaceImage(
        device="cpu", model_name=name, cache_all_layers=True
    )
    out = next(iter(feat._get_data([cat_event])))
    assert out.shape == (5, 512)


def test_torch_hub_model_on_cat(cat_event: ns.events.Image) -> None:
    try:
        model = th.TorchHubModel(name="alexnet")
    except urllib.error.HTTPError:
        pytest.skip("torchhub rate limit")
    data = model.transforms(cat_event.read())
    assert data.shape == (3, 224, 224)
    out = torch.nn.functional.softmax(model(data[None, ...]), dim=1)
    assert out.shape == (1, 1000)
    p = out[0].detach().numpy()
    ind = np.argmax(p)
    assert ind == 281, "Should be index of the cat label (281: tabby, tabby cat)"
    assert pytest.approx(p[ind], rel=0.001) == 0.483


def test_torch_hub_model() -> None:
    models = list(th.TorchHubModel.REGISTER)
    name = models[np.random.choice(len(models))]
    print(f"Testing {name}")
    try:
        model = th.TorchHubModel(name=name)
    except urllib.error.HTTPError:
        pytest.skip("torchhub rate limit")
    # normally you should use transforms from images
    data = torch.rand(2, 3, model.resize, model.resize)
    out = model.hidden_states(data)
    assert len(out) > 2


@pytest.mark.parametrize(
    "device", ["cpu"] + (["cuda"] if torch.cuda.is_available() else [])
)
def test_different_size_images(tmp_path: Path, device: tp.Literal["cpu", "cuda"]) -> None:
    kwargs: tp.Dict[str, tp.Any] = dict(start=0, duration=1, timeline="blublu")
    events = [ns.events.Image(**kwargs, filepath=tmp_path / f"{k}.png") for k in range(2)]
    for k, e in enumerate(events):
        create_image(Path(e.filepath), ((k + 1) * 128,) * 2)
    df = pd.DataFrame([e.to_dict() for e in events])
    name = "facebook/dinov2-small-imagenet1k-1-layer"
    if device == "cuda":
        name = "timm/resnet18.a1_in1k"
    feat = im.ExtendedHuggingFaceImage(
        device=device,
        model_name=name,
        aggregation="average",
    )
    feat.prepare(df)


def test_extended_video_image_latent(
    video_event: ns.events.Video, tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    name = "torchhub/alexnet"
    imparams = {"device": "cpu", "model_name": name, "infra": {"keep_in_ram": False}}
    video = im.ExtendedHuggingFaceVideo(
        frequency=0.5, infra={"folder": cache}, image=imparams  # type: ignore
    )
    out = video(video_event, start=0.0, duration=4)
    assert isinstance(out, torch.Tensor)
    assert out.shape == (4096, 2)
