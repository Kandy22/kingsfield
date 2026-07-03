import os

import numpy as np
from sklearn.linear_model import RidgeClassifierCV
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader

import neuralset as ns
from neuralset.data import StudyLoader

BUTTON_MAPPING = {
    's': 0, 'o': 1, 't': 2, 'e': 3, 'n': 4, 'c': 5, 'i': 6, 'a': 7, '<space>': 8,
    'd': 9, 'l': 10, 'r': 11, 'b': 12, '<special>': 13, 'z': 14, 'v': 15, 'f': 16,
    'm': 17, 'u': 18, 'h': 19, 'p': 20, 'g': 21, 'q': 22, 'w': 23, 'x': 24, 'y': 25,
    'j': 26, 'k': 27, '<number>': 28
}
inverted_mapping = {v: k for k, v in BUTTON_MAPPING.items()}

PROJECT_NAME = "pinet_decoding"
_BRAINAI_ROOT = os.environ.get("BRAINAI_ROOT", os.path.expanduser("~/brainai"))
_DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.join(_BRAINAI_ROOT, "data"))
CACHE = os.environ.get("BRAINAI_CACHE", os.path.join(_BRAINAI_ROOT, "cache", PROJECT_NAME))
MODALITY = "Meg"


def sentence_split(sentence_uids):
    """Train/test split at sentence level."""
    unique_sents = np.unique(sentence_uids)
    train_s, test_s = train_test_split(unique_sents, test_size=0.2, random_state=42)
    return train_s, test_s


def filter_by_uid(X, y, uids, target_uids):
    mask = np.isin(uids, target_uids)
    return X[mask], y[mask], uids[mask]


if __name__ == "__main__":
    events = StudyLoader(
        name=f"Pinet2024{MODALITY}",
        path=os.environ.get("BRAINAI_STUDIES_PATH", os.path.join(_DATA_ROOT, "studies")),
        infra={"folder": CACHE},
        query="subject.isin(['Pinet2024Meg/S1', 'Pinet2024Meg/S2', 'Pinet2024Meg/S3'])"
    ).build()

    # neuro feature extractor
    neuro = ns.features.Meg(
        frequency=100,
        filter=(0.1, 40.0),
        baseline=(0.0, 0.5),
        infra={"folder": CACHE, "cluster": None},
        scaler="StandardScaler",
    )

    # label encoder
    button = ns.features.LabelEncoder(
        predefined_mapping=BUTTON_MAPPING,
        aggregation="trigger",
        event_types="Button",
        event_field="button",
        return_one_hot=False,
    )

    neuro.prepare(events)
    button.prepare(events)
    features = {"neuro": neuro, "button": button}

    results = {}

    for subject in events["subject"].unique():
        print(f"Subject: {subject}")

        segments = ns.segments.list_segments(
            events,
            (events["type"] == "Button") & (events["subject"] == subject),
            duration=1.0,
            start=-0.5,
        )

        dataset = ns.SegmentDataset(features, segments)
        dataloader = DataLoader(dataset, batch_size=10**9, num_workers=4,
                                collate_fn=dataset.collate_fn)

        batch = next(iter(dataloader))
        print("Loaded.")

        # sentence uid
        sentence_uids = np.array([
            f"{seg._trigger['trial_id']}_{seg._trigger['timeline']}"
            for seg in batch.segments
        ])

        # data
        X = batch.data["neuro"].numpy().astype(np.float32)
        y = batch.data["button"].numpy().astype(np.int64).flatten()

        # split at sentence level
        train_s, test_s = sentence_split(sentence_uids)

        X_train, y_train, _ = filter_by_uid(X, y, sentence_uids, train_s)
        X_test, y_test, test_uids = filter_by_uid(X, y, sentence_uids, test_s)

        # Fixed decoding timepoint
        t = 54
        print(f"Decoding at time index t={t}")

        X_train_t = X_train[:, :, t]
        X_test_t  = X_test[:, :, t]

        # Train single model
        clf = RidgeClassifierCV(
            alphas=np.logspace(-2, 8, 11),
            store_cv_values=True
        )
        clf.fit(X_train_t, y_train)

        # Predict test
        y_pred = clf.predict(X_test_t)

        # Save: prediction + sentence_uid for each test sample
        # Here we do not group, we keep it sample-wise exactly as asked
        test_outputs = [
            {
                "sentence_uid": uid,
                "pred_class": int(pred),
                "pred_symbol": inverted_mapping[int(pred)],
                "gt_class": int(gt),
                "gt_symbol": inverted_mapping[int(gt)],
            }
            for uid, pred, gt in zip(test_uids, y_pred, y_test)
        ]

        results[subject] = {
            "time_index": t,
            "test_predictions": test_outputs,
        }

    print(results)