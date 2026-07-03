# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Defines the main classes used in the experiment.

We suggest the following structure:
- `Data`: configures dataset and features to return DataLoaders
- `Trainer`: creates the deep learning model and exposes a `fit` and `test` methods
- `Experiment`: main class that defines the experiment to run by using `Data` and `Trainer`
"""

import typing as tp
from pathlib import Path

import lightning.pytorch as pl
import pydantic
from lightning.pytorch.callbacks import (
    EarlyStopping,
    LearningRateMonitor,
    ModelCheckpoint,
)
from lightning.pytorch.loggers import WandbLogger
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader

import neuralset as ns
from neuraltrain import LightningOptimizerConfig, LossConfig, MetricConfig, ModelConfig
from neuraltrain.utils import BaseExperiment, WandbInfra

from .pl_module import BrainModule


class Data(pydantic.BaseModel):
    """Handles configuration and creation of DataLoaders from dataset and features."""

    model_config = pydantic.ConfigDict(extra="forbid")

    study: ns.data.StudyLoader
    neuro: ns.features.FeatureConfig
    feature: ns.features.FeatureConfig
    valid_size: float = 0.2
    test_size: float = 0.2
    valid_seed: int | None = None
    # Dataset
    start: float = -0.5
    duration: float = 1.4
    batch_size: int = 64
    num_workers: int = 0
    seed: int | None = None

    def build(self) -> tuple[dict[str, DataLoader], int]:
        events = self.study.build()

        # Split into train/valid/test sets
        stimulus_events = events[events.type == self.feature.name]
        n_classes = stimulus_events.code.nunique()
        train_inds, test_inds = train_test_split(
            stimulus_events.index,
            test_size=self.test_size,
            random_state=self.seed,
            stratify=stimulus_events.trigger,
        )
        train_inds, valid_inds = train_test_split(
            train_inds,
            test_size=self.valid_size,
            random_state=self.valid_seed,
            stratify=stimulus_events.loc[train_inds].trigger,
        )
        events.loc[train_inds, "split"] = "train"
        events.loc[valid_inds, "split"] = "valid"
        events.loc[test_inds, "split"] = "test"

        event_summary = (
            events.reset_index()
            .groupby(["split", "type"])[["index", "subject", "filepath", "code"]]
            .nunique()
        )
        print("Event summary: \n", event_summary)

        self.neuro.prepare(events)
        features = {"input": self.neuro, "target": self.feature}

        # Prepare dataloaders
        loaders = {}
        for split in ["train", "valid", "test"]:
            segments = ns.segments.list_segments(
                events,
                idx=events.split == split,
                start=self.start,
                duration=self.duration,
            )
            dataset = ns.SegmentDataset(features=features, segments=segments)
            loaders[split] = DataLoader(
                dataset,
                collate_fn=dataset.collate_fn,
                batch_size=self.batch_size,
                shuffle=split == "train",
                num_workers=self.num_workers,
            )

        return loaders, n_classes


class Experiment(BaseExperiment):
    """Defines the main experiment pipeline including data loading and training/evaluation."""

    data: Data
    # Reproducibility
    seed: int = 33
    # Model
    brain_model_config: ModelConfig
    load_checkpoint: bool = True
    # Loss
    loss: LossConfig
    # Optimization
    optim: LightningOptimizerConfig
    # Metrics
    metrics: list[MetricConfig]
    # Hardware
    strategy: str | None = "auto"
    accelerator: str = "gpu"
    # Optim
    n_epochs: int = 10
    patience: int = 5
    limit_train_batches: int | None = None
    # Others
    enable_progress_bar: bool = True
    log_every_n_steps: int | None = None
    fast_dev_run: bool = False
    # Eval
    checkpoint_path: str | None = None
    test_only: bool = False
    save_checkpoints: bool = False
    # Internal properties
    _trainer: pl.Trainer | None = None
    _brain_module: BrainModule | None = None
    _logger: WandbLogger | None = None

    # Others
    infra: WandbInfra = WandbInfra(version="1")

    def model_post_init(self, __context: tp.Any) -> None:
        if self.infra.folder is None:
            msg = "infra.folder needs to be specified to save the results."
            raise ValueError(msg)
        # Update Trainer parameters based on infra
        self.data.num_workers = self.infra.cpus_per_task

    def _get_checkpoint_path(self) -> Path | None:
        # Setup torch-lightning module
        if not self.load_checkpoint:
            return None
        if self.checkpoint_path is not None:
            checkpoint_path = Path(self.checkpoint_path)
            assert (
                checkpoint_path.exists()
            ), f"Checkpoint path {checkpoint_path} does not exist."
        else:
            checkpoint_path = Path(self.infra.folder) / "last.ckpt"
        if checkpoint_path.exists() and self.load_checkpoint:
            print(f"\nLoading model from {checkpoint_path}\n")
            return checkpoint_path
        else:
            print(f"\nNo checkpoint found at {checkpoint_path}\n")
            return None

    def _setup_trainer(self) -> pl.Trainer:
        callbacks = [
            EarlyStopping(monitor="val_loss", mode="min", patience=self.patience),
            LearningRateMonitor(logging_interval="epoch"),
        ]

        if self.save_checkpoints:
            callbacks.append(
                ModelCheckpoint(
                    save_last=True,
                    save_top_k=1,
                    dirpath=self.infra.folder,
                    filename="best",
                    monitor="val_loss",
                    save_on_train_epoch_end=True,
                )
            )
        trainer = pl.Trainer(
            strategy=self.strategy,
            devices=self.infra.gpus_per_node,
            accelerator=self.accelerator,
            max_epochs=self.n_epochs,
            limit_train_batches=self.limit_train_batches,
            enable_progress_bar=self.enable_progress_bar,
            log_every_n_steps=self.log_every_n_steps,
            fast_dev_run=self.fast_dev_run,
            callbacks=callbacks,
            logger=self._logger,
            enable_checkpointing=self.save_checkpoints,
        )
        return trainer

    def fit(
        self, train_loader: DataLoader, valid_loader: DataLoader, n_classes: int
    ) -> None:
        # Initialize brain model
        batch = next(iter(train_loader))
        n_in_channels = batch.data["input"].shape[1]
        brain_model = self.brain_model_config.build(
            n_in_channels=n_in_channels, n_outputs=n_classes
        )
        self._brain_module = BrainModule(
            model=brain_model,
            loss=self.loss.build(),
            optim_config=self.optim,
            metrics={metric.log_name: metric.build() for metric in self.metrics},
            max_epochs=self.n_epochs,
        )
        self._trainer = self._setup_trainer()

        self._trainer.fit(
            model=self._brain_module,
            train_dataloaders=train_loader,
            val_dataloaders=valid_loader,
            ckpt_path=self._get_checkpoint_path(),
        )

    def test(self, test_loader: DataLoader) -> None:
        self._trainer.test(self._brain_module, dataloaders=test_loader)

    @infra.apply
    def run(self):
        self._logger = (
            self.infra.wandb_config.build(
                save_dir=self.infra.folder,
                xp_config=self.model_dump(),
                id=f"{self.infra.wandb_config.group}-{self.infra.uid().split('-')[-1]}",  # Generate our own id so we can easily relaunch a crashed/failed wandb run
            )
            if self.infra.wandb_config
            else None
        )

        pl.seed_everything(self.seed, workers=True)
        loaders, n_classes = self.data.build()

        if not self.test_only:
            self.fit(loaders["train"], loaders["valid"], n_classes=n_classes)
        self.test(loaders["test"])

        return self._trainer
