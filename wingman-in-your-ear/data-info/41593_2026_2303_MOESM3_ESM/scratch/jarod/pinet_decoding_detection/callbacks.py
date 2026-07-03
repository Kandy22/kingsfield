import json
import os

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


class LogDetections(Callback):
    """
    Callback to log Logits, Labels, and Detected Peaks for every sentence 
    in the validation/test sets to a JSON file.
    """

    def __init__(self):
        super().__init__()
        self.val_data = {}
        self.test_data = {}

    def on_validation_epoch_start(self, trainer, pl_module):
        # Reset storage at start of epoch
        self.val_data = {}

    def on_test_epoch_start(self, trainer, pl_module):
        self.test_data = {}

    def _process_batch(self, outputs, batch, storage_dict):
        """Helper to process batch data and update the storage dictionary."""
        y_pred, y_true, y_pred_peaks = outputs

        # Ensure we are working with CPU tensors for serialization
        y_pred = y_pred.detach().cpu()
        y_true = y_true.detach().cpu()
        y_pred_peaks = y_pred_peaks.detach().cpu()

        # Iterate over the batch
        # batch_size is dimension 0
        for i in range(len(batch.segments)):
            
            # 1. Get Sentence UID from the segment trigger
            # Assuming uniqueness: one UID appears only once per epoch
            segment = batch.segments[i]
            sentence_uid = segment._trigger.get("sentence_UID", f"unknown_{i}")

            # 2. Extract Data (convert to Python lists for JSON)
            # Squeeze is helpful if shapes are (T, 1) -> (T,)
            logits_list = y_pred[i].squeeze().tolist()
            labels_list = y_true[i].squeeze().int().tolist()
            peaks_list = y_pred_peaks[i].squeeze().int().tolist()

            # 3. Store in Dictionary
            storage_dict[sentence_uid] = {
                "logits": logits_list,
                "labels": labels_list,
                "peaks": peaks_list
            }

    def on_validation_batch_end(
        self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0
    ):
        self._process_batch(outputs, batch, self.val_data)

    def on_test_batch_end(
        self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx=0
    ):
        self._process_batch(outputs, batch, self.test_data)

    def on_validation_epoch_end(self, trainer, pl_module):
        self._save_to_json(trainer, self.val_data, "val_all_sentences.json")

    def on_test_epoch_end(self, trainer, pl_module):
        self._save_to_json(trainer, self.test_data, "test_all_sentences.json")

    def _save_to_json(self, trainer, data, filename):
        """Helper to save the dictionary to disk."""
        save_dir = os.path.join(trainer.logger.save_dir, "callbacks")
        os.makedirs(save_dir, exist_ok=True)
        
        file_path = os.path.join(save_dir, filename)
        
        # Atomic write or just standard write
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=None) # indent=None to save space (files will be huge)
            # If you prefer readability over file size, use indent=4
        except Exception as e:
            print(f"Error saving detection logs: {e}")