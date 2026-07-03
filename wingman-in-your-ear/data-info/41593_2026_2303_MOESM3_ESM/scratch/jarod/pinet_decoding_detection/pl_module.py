# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Custom lightning module that wraps a pytorch model.
"""
from pathlib import Path

import lightning.pytorch as pl
import torch
from scipy.signal import find_peaks
from torch import nn
from torchmetrics import Metric

from neuralset.dataloader import SegmentData

NUM_CLASSES = 29

class BrainModule(pl.LightningModule):
    """Torch-lightning module for M/EEG model training."""

    def __init__(
        self,
        model: nn.Module,
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
    ):
        super().__init__()
        self.model = model
        self.x_name, self.y_name = x_name, y_name
        self.checkpoint_path = checkpoint_path

        # To store last layer
        self.embeddings = None
        self.transformer_unique_uids = None
        self.sc_embeddings = None

        # Optimizer
        self.lr = lr
        self.max_epochs = max_epochs
        self.grad_max_norm = grad_max_norm
        self.weight_decay = weight_decay
        self.use_scheduler = use_scheduler
        self.scheduler_type = scheduler_type
        self.optimizer = optimizer

        self.loss = loss
        self.metrics = nn.ModuleDict(
            {split + "_" + k: v for k, v in metrics.items() for split in ["val", "test"]}
        )

        self.save_hyperparameters(ignore=["model", "loss"])
        self.linear = nn.Linear(model.out_channels, 1)

    def _use_peaks(self, y_pred, step_name):
        THRESHOLD = 0.5
        FREQ = 50  
        MIN_DIST_MS = 100 
        min_dist_samples = int((MIN_DIST_MS / 1000) * FREQ)

        # Convert Logits -> Probabilities -> Numpy (B, T)
        probs = torch.sigmoid(y_pred).detach().cpu().numpy()
        
        # Create a placeholder for peak locations (same shape as y_true)
        peaks_mask = torch.zeros_like(y_pred, device=self.device)

        for i in range(probs.shape[0]):
            found_peaks, _ = find_peaks(
                probs[i], 
                height=THRESHOLD, 
                distance=min_dist_samples
            )
            
            # Fill the mask at the found indices
            if len(found_peaks) > 0:
                peaks_mask[i, found_peaks] = 1.0

        # Optional: Log the average number of peaks found per window
        self.log(
            f"{step_name}_avg_peaks_count",
            peaks_mask.sum(dim=1).mean(),
            on_step=False,
            on_epoch=True,
            batch_size=y_pred.shape[0]
        )

        return peaks_mask

    def forward(self, batch: SegmentData):
        x = batch.data["neuro"]
        subject_ids = batch.data["subject_id"] if "subject_id" in batch.data else None
        channel_positions = (
            batch.data["channel_positions"] if "channel_positions" in batch.data else None
        )
        y_pred = self.model(x, subject_ids, channel_positions).permute(0, 2, 1)
        y_pred = self.linear(y_pred)
        
        return y_pred


    def _run_step(self, batch: SegmentData, batch_idx, step_name):
        y_true = batch.data[self.y_name].squeeze(1)

        # Aggregation = sum : if there is an overlap: 2->1 and warning
        if (y_true == 2).any():
            print("WARNING: Found value '2' in y_true — converting to '1'.")
        y_true = torch.where(y_true == 2, torch.tensor(1, device=y_true.device), y_true)
    
        y_pred = self.forward(batch).squeeze(-1)

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

        y_pred_probs = torch.sigmoid(y_pred)
        y_pred_peaks = self._use_peaks(y_pred, step_name)

        # Check if we actually have positive labels in this batch
        num_positives = y_true.sum().item()
        total_elements = y_true.numel()
        ratio = num_positives / total_elements

        print(f"Batch Stats -> Positives: {num_positives} | Total: {total_elements} | Ratio: {ratio:.5f}")

        if num_positives == 0:
            print("WARNING: Batch contains NO targets!")

        probs = torch.sigmoid(y_pred)
        max_prob = probs.max().item()
        avg_prob = probs.mean().item()

        print(f"Pred Stats -> Max Prob: {max_prob:.5f} | Avg Prob: {avg_prob:.5f}")

        # Compute metrics
        for metric_name, metric in self.metrics.items():
            if metric_name.startswith(step_name):
                metric.update(y_pred_probs, y_true)
                self.log(
                    metric_name,
                    metric,
                    on_step=False,
                    on_epoch=True,
                    prog_bar=True,
                    logger=True,
                    batch_size=y_pred.shape[0],
                )

        return loss, y_pred, y_true, y_pred_peaks

    def training_step(self, batch: SegmentData, batch_idx):
        loss, _, _, _ = self._run_step(batch, batch_idx, step_name="train")
        return loss

    def validation_step(self, batch: SegmentData, batch_idx):
        _, y_pred, y_true, y_pred_peaks = self._run_step(batch, batch_idx, step_name="val")
        return y_pred, y_true, y_pred_peaks

    def test_step(self, batch: SegmentData, batch_idx):
        _, y_pred, y_true, y_pred_peaks = self._run_step(batch, batch_idx, step_name="test")
        return y_pred, y_true, y_pred_peaks

    def configure_optimizers(self):
        if hasattr(self.optimizer, "scheduler"):
            self.optimizer.scheduler.kwargs["total_steps"] = (
                self.trainer.estimated_stepping_batches
            )
        optimizer = self.optimizer.build(self.parameters())
        return optimizer

