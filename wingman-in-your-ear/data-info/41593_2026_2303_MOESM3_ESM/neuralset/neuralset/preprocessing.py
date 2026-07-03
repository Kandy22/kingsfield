# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

# pylint: disable=super-init-not-called

import logging
import typing as tp
from abc import abstractmethod

import numpy as np
import pydantic
import sklearn.preprocessing
import torch
from sklearn.decomposition import IncrementalPCA
from tqdm import tqdm

from neuralset.dataloader import MultiSegmentData, SegmentData

from .dataloader import SegmentDataset

logger = logging.getLogger(__name__)


class SklearnTransform(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    @abstractmethod
    def build(self) -> tp.Any:
        raise NotImplementedError


class Scaler(SklearnTransform):
    name: tp.Literal["Scaler"] = "Scaler"
    kind: tp.Literal["StandardScaler", "MinMaxScaler", "MaxAbsScaler"] = "StandardScaler"

    def build(self) -> tp.Any:
        return getattr(sklearn.preprocessing, self.kind)()


class PCA(SklearnTransform):
    name: tp.Literal["PCA"] = "PCA"
    n_components: int | None = None
    whiten: bool = True

    def build(self) -> tp.Any:
        return IncrementalPCA(n_components=self.n_components, whiten=self.whiten)


global SKlearnModelConfig  # pylint: disable=global-statement
SklearnTransformConfig = tp.Annotated[  # type: ignore
    tp.Union[
        tuple(x for x in SklearnTransform.__subclasses__())
    ],  # if "name" in x.model_fields)],
    pydantic.Field(discriminator="name"),  # serves for pydantic
]


class PreprocDataset(SegmentDataset):

    def __init__(self, dataset: SegmentDataset, preprocessors: dict[str, tp.Any]) -> None:
        self.dataset = dataset
        self.preprocessors = preprocessors

    def collate_fn(self, batch: tp.List[tp.Any]) -> tp.Any:
        return self.dataset.collate_fn(batch)

    def __len__(self) -> int:
        return len(self.dataset)

    def __getitem__(self, idx: int) -> SegmentData | MultiSegmentData:  # type: ignore
        segment_data = self.dataset[idx]
        for name, preprocessor in self.preprocessors.items():
            data = segment_data.data[name]
            original_shape, dtype = [
                s for i, s in enumerate(data.shape) if i != 1
            ], data.dtype
            preprocessed = preprocessor.transform(flatten_transpose(data))
            preprocessed = unflatten_untranspose(preprocessed, original_shape, dtype)
            segment_data.data[name] = preprocessed
        return segment_data


class Preprocessor(pydantic.BaseModel):
    """
    Preprocessors are applied to instances of neuralset.SegmentDataset.
    Their API follows the scikit-learn logic, using fit, transform, and fit_transform methods.
    Typically, we apply the fit method on the training set, and then transform the training, validation, and test sets.

    Parameters
    ----------
    models: dict[str, SklearnTransformConfig]
        A dictionary of preprocessors to apply to the dataset.
    batch_size: int
        The batch size to use when fitting the preprocessors.
    num_workers: int
        The number of workers to use when fitting the preprocessors.
    num_samples: int | None
        The number of samples to use when fitting the preprocessors.
    """

    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    models: dict[str, SklearnTransformConfig]  # type: ignore
    batch_size: int = 1024
    num_workers: int = 0
    num_samples: int | None = None

    _models: dict[str, tp.Any] = pydantic.PrivateAttr()

    def fit(self, dataset: SegmentDataset) -> None:
        """Scales features using the provided preprocessors.
        The preprocessors are stored in the dataset for later use in the dataloader.
        """
        models = {}
        if not all([name in dataset.features for name in self.models]):
            raise ValueError(
                f"Some features to preprocess ({self.models}) are not in the dataset features ({dataset.features})"
            )
        for name in self.models:
            models[name] = self.models[name].build()  # type: ignore
        batch_size = min(self.batch_size, len(dataset))
        if self.num_samples is not None:
            batch_size = min(batch_size, self.num_samples)
        dataloader = dataset.build_dataloader(
            num_workers=self.num_workers,
            batch_size=batch_size,
            shuffle=True,
            drop_last=True,
        )
        num_batches = (
            self.num_samples // batch_size if self.num_samples else len(dataloader)
        )
        for i, batch in enumerate(
            tqdm(dataloader, desc="Fitting preprocessors", total=num_batches)
        ):
            if i >= num_batches:
                break
            for name, data in batch.data.items():
                if name in models:
                    models[name].partial_fit(flatten_transpose(data))
        self._models = models

    def transform(self, dataset: SegmentDataset) -> PreprocDataset:
        """Transforms the dataset using the stored models."""
        if self._models is None:
            raise RuntimeError("Scalers are not fitted yet. Call fit() first.")
        dataset = PreprocDataset(dataset, self._models)
        return dataset

    def fit_transform(self, dataset: SegmentDataset) -> PreprocDataset:
        """Fits the models and transforms the dataset."""
        self.fit(dataset)
        return self.transform(dataset)


# utilities


def flatten_transpose(X: torch.Tensor) -> np.ndarray:
    """Transpose and flatten to have (n_total_examples, n_latent_dims)."""
    if X.ndim == 1:
        X = X.unsqueeze(1)
    elif X.ndim > 2:
        X = X.transpose(1, -1).flatten(end_dim=-2)
    return X.numpy()


def unflatten_untranspose(
    X: np.ndarray, original_shape: list[int], dtype: torch.dtype = torch.float32
) -> torch.Tensor:
    """Reshape to original shape."""
    out = torch.tensor(X, dtype=dtype)
    out = out.unflatten(dim=0, sizes=original_shape).transpose(1, -1)
    return out
