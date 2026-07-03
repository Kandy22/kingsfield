# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Custom lightning module that wraps a pytorch model.
"""
import random
from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import torch
from torch import nn
from torchmetrics import Metric

from neuralset.dataloader import SegmentData

NUM_CLASSES = 29

class BrainModule(pl.LightningModule):
    """Torch-lightning module for M/EEG model training."""

    def __init__(
        self,
        model: nn.Module,
        transformer: nn.Module,
        loss: nn.Module,
        metrics: dict[str, Metric],
        x_name: str = "neuro",
        y_name: str = "feature",
        lr: float = 1e-3,
        max_epochs: int = 100,
        grad_max_norm: float = 1.0,
        weight_decay: float = 0.001,
        checkpoint_path: Path | None = None,
        use_scheduler: bool = True,
        optimizer: None = None,
        intermediary_layer_study: bool = False,
        scheduler_type: str = "CosineAnnealingLR",
        channels_study: bool = False,
        channels_peripheral: bool = False,
        channels_central: bool = False,
        n_channels: int | None = None,
        second_step: bool = False,
    ):
        super().__init__()
        self.model = model
        self.transformer = transformer
        if "SimpleConv" in self.model.__class__.__name__:
            self.linear = nn.Linear(model.out_channels, NUM_CLASSES)
        self.x_name, self.y_name = x_name, y_name
        self.checkpoint_path = checkpoint_path

        # To store last layer
        self.embeddings = None
        self.transformer_unique_uids = None
        self.sc_embeddings = None

        self.lr = lr
        self.max_epochs = max_epochs
        self.grad_max_norm = grad_max_norm
        self.weight_decay = weight_decay
        self.use_scheduler = use_scheduler
        self.scheduler_type = scheduler_type
        self.optimizer = optimizer
        self.second_step = second_step
        self.channels_study = channels_study
        self.channels_peripheral = channels_peripheral
        self.channels_central = channels_central
        self.n_channels = n_channels

        peripheral_indexes = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 33, 34, 35, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 119, 122, 126, 127, 128, 129, 130, 131, 132, 133, 134, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 213, 214, 215, 216, 217, 218, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 251, 263, 264, 265, 266, 267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280, 281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296, 297, 298, 299, 300, 301, 302, 303, 304, 305]
        central_indexes = [30, 31, 32, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 120, 121, 123, 124, 125, 135, 136, 137, 182, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 246, 247, 248, 249, 250, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262]

        if self.channels_study:
            if self.channels_peripheral:
                self.selected_indexes = random.sample(peripheral_indexes, len(central_indexes))
            elif self.channels_central:
                self.selected_indexes = central_indexes
            else:
                self.selected_indexes = random.sample(range(306), self.n_channels)

        self.loss = loss
        self.metrics = nn.ModuleDict(
            {split + "_" + k: v for k, v in metrics.items() for split in ["val", "test"]}
        )

        self.save_hyperparameters(ignore=["model", "loss"])

        self.embedding_store = EmbeddingStore()

    def forward(self, batch: SegmentData):
        x = batch.data["neuro"]
        subject_ids = batch.data["subject_id"] if "subject_id" in batch.data else None
        channel_positions = (
            batch.data["channel_positions"] if "channel_positions" in batch.data else None
        )

        model_name = self.model.__class__.__name__
        if "SimpleConv" in model_name:
            y_pred = self.model(x, subject_ids, channel_positions)
        elif model_name == "EEGNet":
            y_pred = self.model(x)
        elif model_name in ["LinearModel"]:
            y_pred = self.model(x, subject_ids)
        else:
            raise ValueError(f"Unknown model {model_name}")
        return y_pred

    def transformer_forward(self, batch, y_pred):
        sentence_uids = np.array(
            [
                f"{segment._trigger['trial_id']}_{segment._trigger['timeline']}"
                for segment in batch.segments
            ]
        )
        unique_uids, sentence_idx = np.unique(sentence_uids, return_index=True)
        unique_uids = unique_uids[np.argsort(sentence_idx)]
        grouped_y_pred = []
        for uid in unique_uids:
            indices = [i for i, s in enumerate(sentence_uids) if s == uid]
            grouped_y_pred.append(torch.stack([y_pred[i] for i in indices]))
        max_len = max([len(y) for y in grouped_y_pred])
        transformer_input = torch.zeros(len(grouped_y_pred), max_len, y_pred.shape[1]).to(
            y_pred.device
        )
        mask = torch.zeros(len(grouped_y_pred), max_len).to(y_pred.device)
        for i, y in enumerate(grouped_y_pred):
            transformer_input[i, : len(y)] = y
            mask[i, : len(y)] = 1

        transformer_output = self.transformer(transformer_input, mask=mask.bool())

        out = []
        for i, y in enumerate(grouped_y_pred):
            out.extend(transformer_output[i][: len(y)])
        out = torch.stack(out)

        # Save embedding layer
        self.embeddings = out

        self.transformer_unique_uids = np.array(unique_uids)

        # Linear layer to go back into the num classes space
        output = self.linear(out)

        return output

    def _run_step(self, batch: SegmentData, batch_idx, step_name):
        if self.channels_study:
            batch.data["neuro"] = batch.data["neuro"][:, self.selected_indexes, :]
            batch.data['channel_positions'] = batch.data['channel_positions'][:, self.selected_indexes, :]

        y_true = batch.data[self.y_name].squeeze(1)
        y_pred = self.forward(batch)

        if self.transformer is not None:
            self.sc_embeddings = y_pred.clone()
        
        if self.transformer is None:
            loss = self.loss(y_pred, y_true)
            self.log(
                f"{step_name}_loss",
                loss,
                on_step=True if step_name == "train" else False,
                on_epoch=True,
                logger=True,
                prog_bar=True,
                batch_size=y_pred.shape[0],
            )

        if self.transformer is not None:
            y_pred = self.transformer_forward(batch, y_pred)
            transformer_loss = self.loss(y_pred, y_true)
            self.log(
                f"{step_name}_transformer_loss",
                transformer_loss,
                on_step=True if step_name == "train" else False,
                on_epoch=True,
                logger=True,
                prog_bar=True,
            )
            loss = transformer_loss

        # Compute metrics
        for metric_name, metric in self.metrics.items():
            if metric_name.startswith(step_name):
                metric.update(y_pred, y_true)
                self.log(
                    metric_name,
                    metric,
                    on_step=False,
                    on_epoch=True,
                    prog_bar=True,
                    logger=True,
                    batch_size=y_pred.shape[0],
                )

        return loss, y_pred, y_true

    def training_step(self, batch: SegmentData, batch_idx):
        loss, _, _ = self._run_step(batch, batch_idx, step_name="train")
        return loss

    def validation_step(self, batch: SegmentData, batch_idx):
        _, y_pred, y_true = self._run_step(batch, batch_idx, step_name="val")
        return y_pred, y_true

    def test_step(self, batch: SegmentData, batch_idx):
        _, y_pred, y_true = self._run_step(batch, batch_idx, step_name="test")
        return y_pred, y_true

    def configure_optimizers(self):
        if hasattr(self.optimizer, "scheduler"):
            self.optimizer.scheduler.kwargs["total_steps"] = (
                self.trainer.estimated_stepping_batches
            )
        optimizer = self.optimizer.build(self.parameters())
        return optimizer


class EmbeddingStore:
    def __init__(self):
        self.active = False
        self.embeddings = []  

    def __call__(self, module, input, output):
        if self.active:
            self.embeddings.append(output.detach().cpu())
