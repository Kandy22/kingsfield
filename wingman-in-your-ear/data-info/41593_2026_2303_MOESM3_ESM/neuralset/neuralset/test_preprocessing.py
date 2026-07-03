# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.


import pytest
import torch

import neuralset as ns

from .preprocessing import PreprocDataset, Preprocessor
from .test_dataloader import ExampleDataLoader


@pytest.mark.parametrize("model", ["Scaler", "PCA"])
def test_preproc(model: str) -> None:
    dloader = ExampleDataLoader(
        studies=[{"name": "MneSample2013", "path": ns.CACHE_FOLDER}],  # type: ignore
        event_type="Stimulus",
        features={
            "neuro": {"name": "Meg", "frequency": 100, "aggregation": "single"},  # type: ignore
        },
        batch_size=2,
    ).build()
    dataset = dloader.dataset
    config = {"models": {"neuro": {"name": model}}, "batch_size": 32}
    if model == "PCA":
        config["models"]["neuro"]["n_components"] = 10  # type: ignore
    preprocessor = Preprocessor(**config)  # type: ignore
    scaled_dataset = preprocessor.fit_transform(dataset)  # type: ignore
    assert isinstance(scaled_dataset, PreprocDataset)
    scaled_data = scaled_dataset.as_one_batch().data
    for name in preprocessor.models:
        num_features = scaled_data[name].shape[1] if scaled_data[name].ndim > 1 else 1
        if model == "PCA":
            assert num_features == preprocessor.models[name].n_components  # type: ignore
        elif model == "Scaler":
            if scaled_data[name].ndim <= 2:
                scaled_mean, scaled_std = scaled_data[name].mean(0), scaled_data[
                    name
                ].std(0)
            else:
                scaled_mean, scaled_std = scaled_data[name].mean((0, 2)), scaled_data[
                    name
                ].std((0, 2))
            assert torch.allclose(scaled_mean, torch.zeros(num_features), atol=1e-4)
            assert torch.allclose(scaled_std, torch.ones(num_features), atol=1e-4)
