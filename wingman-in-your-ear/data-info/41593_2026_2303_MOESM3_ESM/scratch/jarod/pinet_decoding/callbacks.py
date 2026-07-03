import copy
import json
import os

import lightning.pytorch as pl
import numpy as np
import torch
from lightning.pytorch.callbacks import Callback

original_mapping = {
    "s": 0,
    "o": 1,
    "t": 2,
    "e": 3,
    "n": 4,
    "c": 5,
    "i": 6,
    "a": 7,
    " ": 8,
    "d": 9,
    "l": 10,
    "r": 11,
    "b": 12,
    "@": 13,
    "z": 14,
    "v": 15,
    "f": 16,
    "m": 17,
    "u": 18,
    "h": 19,
    "p": 20,
    "g": 21,
    "q": 22,
    "w": 23,
    "x": 24,
    "y": 25,
    "j": 26,
    "k": 27,
    "9": 28,
}
inverted_mapping = {v: k for k, v in original_mapping.items()}


class StoreTransformerEmbeddings(Callback):
    def __init__(self):
        self.val_embeddings = []
        self.test_embeddings = []
        self.val_labels_embeddings = []
        self.test_labels_embeddings = []
        self.val_button_unique_ids = []
        self.test_button_unique_ids = []
        self.transformer_test_sentence_uids = []

    def on_validation_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        # Initialize as empty lists
        self.val_embeddings = []
        self.val_labels_embeddings = []
        self.val_button_unique_ids = []

    def on_test_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="test"
    ):
        # Initialize as empty lists
        self.test_embeddings = []
        self.test_labels_embeddings = []
        self.test_button_unique_ids = []

    def on_validation_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="val",
    ):
        y_pred, y_true = outputs
        buttons_unique_ids = np.array(
            [segment._trigger["button_unique_id"] for segment in batch.segments]
        )

        if pl_module.embeddings is not None:
            embedding_array = pl_module.embeddings.detach().cpu().numpy()
            y_true_array = y_true.detach().cpu().numpy()  # Convert to numpy array

            # Append to lists
            self.val_embeddings.append(embedding_array)
            self.val_labels_embeddings.append(y_true_array)
            self.val_button_unique_ids.append(buttons_unique_ids)
        return

    def on_validation_epoch_end(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
        os.makedirs(save_dir, exist_ok=True)

        # Concatenate along the batch dimension (0)
        if self.val_embeddings:
            val_embeddings_concat = np.concatenate(self.val_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_embedding.npy")
            np.save(path, val_embeddings_concat)

        if self.val_labels_embeddings:
            val_labels_concat = np.concatenate(self.val_labels_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_labels_embedding.npy")
            np.save(path, val_labels_concat)

        if self.val_button_unique_ids:
            val_button_ids_concat = np.concatenate(self.val_button_unique_ids, axis=0)
            path = os.path.join(save_dir, f"{step_name}_button_ids.npy")
            np.save(path, val_button_ids_concat)

        return

    def on_test_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="test",
    ):
        y_pred, y_true = outputs
        buttons_unique_ids = np.array(
            [segment._trigger["button_unique_id"] for segment in batch.segments]
        )

        if pl_module.embeddings is not None:
            embedding_array = pl_module.embeddings.detach().cpu().numpy()
            y_true_array = y_true.detach().cpu().numpy()  # Convert to numpy array

            # Append to lists
            self.test_embeddings.append(embedding_array)
            self.test_labels_embeddings.append(y_true_array)
            self.test_button_unique_ids.append(buttons_unique_ids)

        if pl_module.transformer_unique_uids is not None:
            self.transformer_test_sentence_uids.append(pl_module.transformer_unique_uids)
        return

    def on_test_epoch_end(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="test"
    ):
        save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
        os.makedirs(save_dir, exist_ok=True)

        # Concatenate along the batch dimension (0)
        if self.test_embeddings:
            test_embeddings_concat = np.concatenate(self.test_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_embedding.npy")
            np.save(path, test_embeddings_concat)

        if self.test_labels_embeddings:
            test_labels_concat = np.concatenate(self.test_labels_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_labels_embedding.npy")
            np.save(path, test_labels_concat)

        if self.test_button_unique_ids:
            test_button_ids_concat = np.concatenate(self.test_button_unique_ids, axis=0)
            path = os.path.join(save_dir, f"{step_name}_button_ids.npy")
            np.save(path, test_button_ids_concat)

        if self.transformer_test_sentence_uids:
            path = os.path.join(save_dir, f"{step_name}_transformer_sentence_uid.pt")
            torch.save(self.transformer_test_sentence_uids, path)

        return


class IntermediaryEmbeddingStore(Callback):
    def __init__(self):
        self.embeddings = []

    def on_test_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="test",
    ):

        if pl_module.embedding_store is not None:
            embedding_array = pl_module.embedding_store.embeddings
            self.embeddings.extend(embedding_array)

        return


    def on_test_epoch_end(self, trainer, pl_module, step_name="test"):
        if pl_module.embedding_store is not None:
            save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
            save_path = os.path.join(save_dir, f"{step_name}_intermediary_embeddings.pt")
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            torch.save(self.embeddings, save_path)
            self.embeddings = []

class StoreEmbeddings(Callback):
    def __init__(self):
        self.val_embeddings = []
        self.test_embeddings = []
        self.val_labels_embeddings = []
        self.test_labels_embeddings = []
        self.val_button_unique_ids = []
        self.test_button_unique_ids = []

    def on_validation_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        # Initialize as empty lists
        self.val_embeddings = []
        self.val_labels_embeddings = []
        self.val_button_unique_ids = []

    def on_test_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="test"
    ):
        # Initialize as empty lists
        self.test_embeddings = []
        self.test_labels_embeddings = []
        self.test_button_unique_ids = []

    def on_validation_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="val",
    ):
        y_pred, y_true = outputs

        if pl_module.sc_embeddings is not None:
            embedding_array = pl_module.sc_embeddings.detach().cpu().numpy()
            y_true_array = y_true.detach().cpu().numpy()  # Convert to numpy array

            # Append to lists
            self.val_embeddings.append(embedding_array)
            self.val_labels_embeddings.append(y_true_array)
        return

    def on_validation_epoch_end(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
        os.makedirs(save_dir, exist_ok=True)

        # Concatenate along the batch dimension (0)
        if self.val_embeddings:
            val_embeddings_concat = np.concatenate(self.val_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_sc_embedding.npy")
            np.save(path, val_embeddings_concat)

        if self.val_labels_embeddings:
            val_labels_concat = np.concatenate(self.val_labels_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_labels_sc_embedding.npy")
            np.save(path, val_labels_concat)

        return

    def on_test_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="test",
    ):
        y_pred, y_true = outputs

        if pl_module.sc_embeddings is not None:
            embedding_array = pl_module.sc_embeddings.detach().cpu().numpy()
            y_true_array = y_true.detach().cpu().numpy()  # Convert to numpy array

            # Append to lists
            self.test_embeddings.append(embedding_array)
            self.test_labels_embeddings.append(y_true_array)
        return

    def on_test_epoch_end(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="test"
    ):
        save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
        os.makedirs(save_dir, exist_ok=True)

        # Concatenate along the batch dimension (0)
        if self.test_embeddings:
            test_embeddings_concat = np.concatenate(self.test_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_sc_embedding.npy")
            np.save(path, test_embeddings_concat)

        if self.test_labels_embeddings:
            test_labels_concat = np.concatenate(self.test_labels_embeddings, axis=0)
            path = os.path.join(save_dir, f"{step_name}_labels_sc_embedding.npy")
            np.save(path, test_labels_concat)

        return


class LogPreds(Callback):
    def on_validation_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        self.val_predictions = {}
        self.validation_all_sentences = {}

    def on_test_epoch_start(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="test"
    ):
        self.test_predictions = {}
        self.test_all_sentences = {}

    def on_validation_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="val",
    ):
        y_pred, y_true = outputs

        buttons_unique_ids = np.array(
            [segment._trigger["button_unique_id"] for segment in batch.segments]
        )
        sentence_uids = np.array(
            [
                f"{segment._trigger['trial_id']}_{segment._trigger['timeline']}"
                for segment in batch.segments
            ]
        )

        true_sentences = [segment._trigger["sentence"] for segment in batch.segments]

        for y_pred_, y_true_, sentence_uid, sentence, button_unique_id in zip(
            y_pred, y_true, sentence_uids, true_sentences, buttons_unique_ids
        ):

            _, predicted_index = torch.max(y_pred_, dim=0)

            if button_unique_id not in self.val_predictions:
                self.val_predictions[button_unique_id] = {"pred": ""}
            self.val_predictions[button_unique_id]["pred"] = predicted_index.item()
            
            y_pred_list = y_pred_.tolist()
            self.val_predictions[button_unique_id]["logits"] = y_pred_list

            if sentence_uid not in self.validation_all_sentences:
                self.validation_all_sentences[sentence_uid] = {
                    "pred": [],
                    "typed": [],
                    "true": "",
                    "logits": [],
                }

            self.validation_all_sentences[sentence_uid]["pred"].append(
                predicted_index.item()
            )
            self.validation_all_sentences[sentence_uid]["typed"].append(y_true_.item())
            self.validation_all_sentences[sentence_uid]["true"] = sentence

            y_pred_list = y_pred_.tolist()
            self.validation_all_sentences[sentence_uid]["logits"].append(y_pred_list)

        return

    def on_validation_epoch_end(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, step_name="val"
    ):
        save_dir = os.path.join(
            trainer.logger.save_dir,
            f"callbacks",
        )

        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"{step_name}_all_sentences.json")
        with open(file_path, "w") as f:
            json.dump(self.validation_all_sentences, f, indent=4)

        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"{step_name}_predictions.json")
        with open(file_path, "w") as f:
            json.dump(self.val_predictions, f, indent=4)

        return

    def on_test_batch_end(
        self,
        trainer,
        pl_module,
        outputs,
        batch,
        batch_idx,
        dataloader_idx=0,
        step_name="test",
    ):
        y_pred, y_true = outputs

        buttons_unique_ids = np.array(
            [segment._trigger["button_unique_id"] for segment in batch.segments]
        )
        sentence_uids = np.array(
            [
                f"{segment._trigger['trial_id']}_{segment._trigger['timeline']}"
                for segment in batch.segments
            ]
        )
        true_sentences = [segment._trigger["sentence"] for segment in batch.segments]

        for y_pred_, y_true_, sentence_uid, sentence, button_unique_id in zip(
            y_pred, y_true, sentence_uids, true_sentences, buttons_unique_ids
        ):

            _, predicted_index = torch.max(y_pred_, dim=0)

            if button_unique_id not in self.test_predictions:
                self.test_predictions[button_unique_id] = {"pred": ""}
            self.test_predictions[button_unique_id]["pred"] = predicted_index.item()

            y_pred_list = y_pred_.tolist()
            self.test_predictions[button_unique_id]["logits"] = y_pred_list

            if sentence_uid not in self.test_all_sentences:
                self.test_all_sentences[sentence_uid] = {
                    "pred": [],
                    "typed": [],
                    "true": "",
                    "logits": [],
                }

            self.test_all_sentences[sentence_uid]["pred"].append(predicted_index.item())
            self.test_all_sentences[sentence_uid]["typed"].append(y_true_.item())
            self.test_all_sentences[sentence_uid]["true"] = sentence

            y_pred_list = y_pred_.tolist()
            self.test_all_sentences[sentence_uid]["logits"].append(y_pred_list)

        self.on_validation_batch_end(
            trainer, pl_module, outputs, batch, batch_idx, dataloader_idx, step_name
        )

    def on_test_epoch_end(self, trainer: pl.Trainer, pl_module, step_name="test"):
        save_dir = os.path.join(
            trainer.logger.save_dir,
            f"callbacks",
        )
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"{step_name}_all_sentences.json")
        with open(file_path, "w") as f:
            json.dump(self.test_all_sentences, f, indent=4)

        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"{step_name}_predictions.json")
        with open(file_path, "w") as f:
            json.dump(self.test_predictions, f, indent=4)

        return

class JitterWindows(Callback):
    """
    Applies random temporal jitter to existing classification segments 
    during training to make the classifier robust to detection errors.
    """
    def __init__(
        self,
        fs,
        jitter_samples: int = 5, 
    ):
        self.jitter_samples = jitter_samples
        self.fs = fs
        self.original_segments = None # Store ground truth here

    def on_train_start(self, trainer, pl_module):
        dataset = trainer.train_dataloader.dataset
        
        # Deepcopy is essential so we don't modify the backup by reference
        self.original_segments = copy.deepcopy(dataset.segments)
        print(f"[JitterCallback] Saved {len(self.original_segments)} original segments for jittering.")

    def on_train_epoch_start(self, trainer, pl_module):
        """
        At the start of every epoch, generate a new set of jittered segments.
        """
        if self.original_segments is None:
            return

        dataset = trainer.train_dataloader.dataset
        new_segments = []
    
        for seg in self.original_segments:
            shift_samples = np.random.randint(-self.jitter_samples, self.jitter_samples + 1)
            shift_seconds = shift_samples / self.fs
            new_seg = copy.copy(seg)
            new_seg.start = seg.start + shift_seconds
            new_segments.append(new_seg)

        dataset.segments = new_segments







