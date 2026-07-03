import random
import typing as tp
from pathlib import Path

import lightning.pytorch as pl
import numpy as np
import pandas as pd
import pydantic
from lightning.pytorch.callbacks import EarlyStopping, ModelCheckpoint
from lightning.pytorch.loggers import WandbLogger
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from torch import nn
from torch.utils.data import DataLoader

import neuralset as ns
from neuralset.dataloader import SegmentDataset
from neuraltrain.losses import LossConfig
from neuraltrain.metrics import MetricConfig
from neuraltrain.models import ModelConfig
from neuraltrain.optimizers import LightningOptimizerConfig
from neuraltrain.utils import BaseExperiment, WandbInfra

from .callbacks import LogDetections
from .pl_module import BrainModule


def split_events(events, splitting_ratios, seed):
    buttons = events[events["type"] == "Button"]
    unique_sentences = buttons["sentence"].unique()
    random.seed(seed)

    # Step 1: Vectorize sentences and compute similarity matrix
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(unique_sentences)
    similarity_matrix = cosine_similarity(tfidf_matrix)

    # Step 2: Cluster sentences based on similarity threshold
    def strict_cluster_sentences(similarity_matrix, threshold=0.5):
        clusters = []
        visited = set()

        for i in range(similarity_matrix.shape[0]):
            if i in visited:
                continue

            # Start a new cluster with the current sentence
            cluster = {i}
            expanded = True

            while expanded:
                expanded = False
                current_cluster_sentences = list(cluster)
                for idx in current_cluster_sentences:
                    for j in range(similarity_matrix.shape[1]):
                        if j not in cluster and similarity_matrix[idx, j] > threshold:
                            cluster.add(j)
                            expanded = True

            visited.update(cluster)
            clusters.append(list(cluster))

        return clusters

    clusters = strict_cluster_sentences(similarity_matrix)
    random.shuffle(clusters)

    # Step 3: Allocate clusters to splits based on the ratios
    total_rows = len(buttons)
    train_size = int(splitting_ratios[0] * total_rows)
    val_size = int(splitting_ratios[1] * total_rows)
    test_size = total_rows - train_size - val_size  # Remaining size for test

    split_counts = {"train": train_size, "val": val_size, "test": test_size}
    current_split_counts = {"train": 0, "val": 0, "test": 0}
    sentence_to_split = {}

    # Helper function to determine appropriate split for the cluster
    def allocate_split(cluster_size):
        for split in ["train", "val", "test"]:
            if current_split_counts[split] + cluster_size <= split_counts[split]:
                current_split_counts[split] += cluster_size
                return split
        return "test"  # Default to 'test' if the other splits are filled

    # Assign clusters to splits
    for cluster in clusters:
        cluster_sentences = [unique_sentences[idx] for idx in cluster]
        cluster_rows = buttons[buttons["sentence"].isin(cluster_sentences)]
        cluster_size = len(cluster_rows)

        split = allocate_split(cluster_size)
        for sentence in cluster_sentences:
            sentence_to_split[sentence] = split

    # Apply the splits to the original DataFrame
    events["split"] = events["sentence"].map(sentence_to_split)

    return events


def splitter_checker(events, threshold=0.5):
    buttons = events[events["type"] == "Button"]

    train_buttons = buttons[buttons["split"] == "train"]
    val_buttons = buttons[buttons["split"] == "val"]
    test_buttons = buttons[buttons["split"] == "test"]

    unique_train_sentences = train_buttons["sentence"].unique()
    unique_val_sentences = val_buttons["sentence"].unique()
    unique_test_sentences = test_buttons["sentence"].unique()

    unique_sentences = np.concatenate(
        [unique_train_sentences, unique_val_sentences, unique_test_sentences]
    )

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(unique_sentences)
    similarity_matrix = cosine_similarity(tfidf_matrix)

    leakage_pairs = []
    sentence_to_index = {sentence: idx for idx, sentence in enumerate(unique_sentences)}

    for train_sentence in unique_train_sentences:
        for val_sentence in unique_val_sentences:
            if (
                similarity_matrix[
                    sentence_to_index[train_sentence], sentence_to_index[val_sentence]
                ]
                > threshold
            ):
                leakage_pairs.append(
                    (
                        train_sentence,
                        val_sentence,
                        similarity_matrix[
                            sentence_to_index[train_sentence],
                            sentence_to_index[val_sentence],
                        ],
                    )
                )

    for train_sentence in unique_train_sentences:
        for test_sentence in unique_test_sentences:
            if (
                similarity_matrix[
                    sentence_to_index[train_sentence], sentence_to_index[test_sentence]
                ]
                > threshold
            ):
                leakage_pairs.append(
                    (
                        train_sentence,
                        test_sentence,
                        similarity_matrix[
                            sentence_to_index[train_sentence],
                            sentence_to_index[test_sentence],
                        ],
                    )
                )

    for val_sentence in unique_val_sentences:
        for test_sentence in unique_test_sentences:
            if (
                similarity_matrix[
                    sentence_to_index[val_sentence], sentence_to_index[test_sentence]
                ]
                > threshold
            ):
                leakage_pairs.append(
                    (
                        val_sentence,
                        test_sentence,
                        similarity_matrix[
                            sentence_to_index[val_sentence],
                            sentence_to_index[test_sentence],
                        ],
                    )
                )

    return leakage_pairs


def preprocessing(events):
    events = events[~events["trial_id"].isin([0.0, 1.0])]

    # Remove all the control data
    control_data = ['Pinet2024Meg/S11122024', 'Pinet2024Meg/S12122024',
       'Pinet2024Meg/S26112024', 'Pinet2024Meg/S27112024',
       'Pinet2024Meg/S28112024']
    events = events[~events['subject'].isin(control_data)]

    # Remove S23: bad participant (he has metal in his body)
    events = events[events['subject'] != 'Pinet2024Meg/S23']

    # Aggregate same participants
    events['subject'] = events['subject'].str.replace('Pinet2024Meg/S18', 'Pinet2024Meg/S1')
    events['subject'] = events['subject'].str.replace('Pinet2024Meg/S14', 'Pinet2024Meg/S4')
    events['subject'] = events['subject'].str.replace('Pinet2024Meg/S10', 'Pinet2024Meg/S5')
    events['subject'] = events['subject'].str.replace('Pinet2024Meg/S21', 'Pinet2024Meg/S5')

    # Map subject to integers + UID for sentences + bad sentence removal
    events["subject"] = pd.factorize(events["subject"])[0]
    events["sentence_UID"] = events["trial_id"].astype(str) + "_" + events["timeline"]
    events = events[
        events["sentence_UID"] != "65.0_Pinet2024Meg_subject-S1_session-1_task-block1"
    ]

    # UID for button events + NaN values for other rows that are not a Button Event
    events["button_count"] = events.groupby("sentence_UID")["type"].transform(
        lambda x: (x == "Button").cumsum()
    )
    events["button_unique_id"] = (
        events["sentence_UID"] + "_" + events["button_count"].astype(str)
    )
    events = events.drop(columns="button_count")
    events.loc[events["type"] != "Button", "button_unique_id"] = np.nan
    events.loc[events["type"] != "Button", "sentence"] = np.nan

    # Test
    buttons = events[events["type"] == "Button"]
    assert len(buttons) == len(buttons["button_unique_id"].unique())

    sentences_uids = buttons["sentence_UID"].unique()
    events = events[events["type"] != "Sentence"]
    grouped_events = events.groupby("sentence_UID")
    updated_sentences = []
    for suid in sentences_uids:
        df = grouped_events.get_group(suid)
        button_events = df[df["type"] == "Button"]
        if not button_events.empty:
            # Create a new sentence event
            sentence = button_events.iloc[0].copy()
            new_duration = button_events["stop"].max() - button_events["start"].min()
            sentence['type'] = 'Sentence'
            sentence["duration"] = new_duration
            sentence["start"] = button_events["start"].min()
            sentence["stop"] = button_events["stop"].max()
            updated_sentences.append(sentence)

    if updated_sentences:
        updated_sentences_df = pd.DataFrame(updated_sentences)
        events = pd.concat([events, updated_sentences_df])
        events.reset_index(drop=True, inplace=True)

    # Test
    sentences = events[(events["type"] == "Sentence") & (events["is_image"] == False)]
    assert len(sentences) == len(sentences["sentence_UID"].unique())

    # Populate correctly the text column of button event and sentence button + word button for word and text for keystroke
    button_df = events[events["type"] == "Button"]
    sentence_dict = button_df.set_index("sentence_UID")["sentence"].to_dict()
    events["text"] = events.apply(
        lambda row: (
            sentence_dict.get(row["sentence_UID"], None)
            if row["type"] == "Sentence"
            else row["text"]
        ),
        axis=1,
    )

    # Sentence Typed Column Creation
    sentence_typed = (
        events[events["type"] == "Button"]
        .groupby("sentence_UID")["button"]
        .apply("".join)
        .reset_index(name="sentence_typed")
    )
    events = events.merge(sentence_typed, on="sentence_UID", how="left")
    events["sentence_typed"] = events.apply(
        lambda row: (
            row["sentence_typed"] if row["type"] in ["Button", "Sentence"] else np.nan
        ),
        axis=1,
    )
    events["sentence_typed"] = events["sentence_typed"].str.replace(
        "<special>", "@", regex=False
    )
    events["sentence_typed"] = events["sentence_typed"].str.replace(
        "<space>", " ", regex=False
    )
    events["sentence_typed"] = events["sentence_typed"].str.replace(
        "<number>", "9", regex=False
    )

    # For EEG to work
    columns_to_drop = [
        "word_id",
        "word_index",
        "trigger",
        "time",
        "pressed",
        "key",
        "is_key",
        "stim",
        "char_id",
        "is_left_key",
        "dropped_char_per",
        "context",
        "char_id",
    ]
    events = events.drop(columns_to_drop, axis=1)


    return events


class Data(pydantic.BaseModel):
    """Handles configuration and creation of DataLoaders from dataset and features."""

    model_config = pydantic.ConfigDict(extra="forbid")

    study: ns.data.StudyLoader
    neuro: ns.features.FeatureConfig
    feature: ns.features.FeatureConfig
    valid_size: float = 0.1
    test_size: float = 0.1

    # Dataset
    start: float = -0.5
    duration: float | None = 1.0  ##
    batch_size: int = 64
    val_batch_size: int = 8192
    test_batch_size: int = 8192
    num_workers: int = 0
    num_classes: int = 29

    # Splitting
    splitting_seed: int | None = None
    splitting_ratios: tuple = (0.8, 0.1, 0.1)

    # Scaling law study
    timeline_study: bool = False
    n_samples: int | None = None
    sentence_study: bool = False
    n_sentences: int | None = None
    subject_study: bool = False
    n_subjects: int | None = None

    def build(self) -> tuple[dict[str, DataLoader], int]:
        neuro_type = self.neuro.event_types

        events = self.study.build()
        events = preprocessing(events)
            
        events = split_events(events, self.splitting_ratios, self.splitting_seed)
        leakage_pairs = splitter_checker(events)

        # Data Leakage Checker
        if leakage_pairs:
            print(
                "Data leakage detected! Pairs of sentences with cosine similarity above 0.5 between different splits:"
            )
            for pair in leakage_pairs:
                print(f"Sentence 1: {pair[0]}")
                print(f"Sentence 2: {pair[1]}")
                print(f"Cosine Similarity: {pair[2]}")
                break
        
        self.neuro.prepare(events)
        self.feature.prepare(events)
        
        subject_id = ns.features.LabelEncoder(event_types=neuro_type, event_field="subject")
        subject_id.__class__.event_types = getattr(ns.events, neuro_type)
        subject_id.prepare(events)

        if neuro_type in ["Meg", "Eeg"]:
            channel_positions = ns.features.ChannelPositions(neuro=self.neuro)
            channel_positions.prepare(events)
            extra_neuro_features = dict(channel_positions=channel_positions)
        else:
            extra_neuro_features = dict()

        features = {
            "neuro": self.neuro,
            "feature": self.feature,
            "subject_id": subject_id,
            **extra_neuro_features,
        }

        ## DATALOADERS CREATION
        loaders = {}
        batch_sizes = {
            "train": self.batch_size,
            "val": self.val_batch_size,
            "test": self.test_batch_size,
        }

        for split, batch_size in batch_sizes.items():
            split_mask = (events.split == split) & (events.type == "Sentence")
            
            segments = ns.segments.list_segments(
                events,
                split_mask,
                start=self.start,
                duration=self.duration,
            )
            dataset = SegmentDataset(
                features=features,
                segments=segments,
                remove_incomplete_segments=True,
                pad_duration=12.0 # Max duration for test sentence is 11.7
            )
            loaders[split] = DataLoader(
                dataset,
                collate_fn=dataset.collate_fn,
                batch_size=batch_size,
                shuffle=split=='train',  
                num_workers=self.num_workers,
            )
        
        return loaders


class Experiment(BaseExperiment):
    """Defines the main experiment pipeline including data loading and training/evaluation."""

    data: Data

    # Reproducibility
    seed: int = 33
    # Model
    brain_model_config: ModelConfig
    load_checkpoint: bool = True
    # Transformer
    transformer_start_epoch: int = 0
    use_transformer: bool = False
    # Loss
    loss: LossConfig
    # Metrics
    metrics: list[MetricConfig]
    # Weights & Biases
    save_checkpoints: bool = True
    # Hardware
    strategy: str = "auto"
    accelerator: str = "gpu"
    # Optim
    n_epochs: int = 10
    patience: int = 5
    lr: float = 1e-3
    grad_max_norm: float = 1.0
    weight_decay: float = 0.001
    limit_train_batches: int | None = None

    use_scheduler: bool = (True,)
    scheduler_type: str = ("CosineAnnealingLR",)
    # Others
    enable_progress_bar: bool = True
    log_every_n_steps: int | None = None
    fast_dev_run: bool = False

    # Channel Study
    channels_study: bool = False,
    channels_peripheral: bool = False,
    channels_central: bool = False,
    n_channels: int | None = None,

    intermediary_layer_study: bool = False

    #Optimizer
    optimizer: LightningOptimizerConfig

    # Internal properties
    _trainer: pl.Trainer | None = None
    _brain_module: BrainModule | None = None
    _logger: WandbLogger | None = None

    # Others
    infra: WandbInfra = WandbInfra(version="1")

    def model_post_init(self, __context: tp.Any) -> None:

        assert (
            self.infra.folder is not None
        ), "infra.folder needs to be specified to save the results."

    def _init_module(
        self, model: nn.Module,
    ) -> pl.LightningModule:
        # Setup torch-lightning module
        checkpoint_path = Path(self.infra.folder) / "last.ckpt"
        if checkpoint_path.exists() and self.load_checkpoint:
            print(f"\nLoading model from {checkpoint_path}\n")  # XXX Use logger
            init_fn = BrainModule.load_from_checkpoint
        else:
            init_fn = BrainModule
            checkpoint_path = None

        pl_module = init_fn(
            model=model,
            loss=self.loss.build(),
            metrics={metric.log_name: metric.build() for metric in self.metrics},
            lr=self.lr,
            max_epochs=self.n_epochs,
            grad_max_norm=self.grad_max_norm,
            weight_decay=self.weight_decay,
            use_scheduler=self.use_scheduler,
            channels_study=self.channels_study,
            channels_peripheral=self.channels_peripheral,
            channels_central=self.channels_central,
            n_channels = self.n_channels,
            optimizer=self.optimizer,
            intermediary_layer_study = self.intermediary_layer_study,
            scheduler_type=self.scheduler_type,
            checkpoint_path=checkpoint_path,
        )

        return pl_module

    def _setup_trainer(self) -> pl.Trainer:
        callbacks = [
            EarlyStopping(monitor="val_f1", mode="max", patience=self.patience),
            LogDetections(),
        ]

        if self.save_checkpoints:
            callbacks.append(
                ModelCheckpoint(
                    save_last=True,
                    save_top_k=1,
                    dirpath=self.infra.folder,
                    filename="best",
                    monitor="val_CER",
                    mode="min",
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
        )
        return trainer

    def fit(
        self,
        train_loader: DataLoader,
        valid_loader: DataLoader,
    ) -> None:
        # Initialize brain model
        batch = next(iter(train_loader))
        n_in_channels = batch.data["neuro"].shape[1]
        n_hidden = self.brain_model_config.hidden

        if self.channels_study:
            n_in_channels = self.n_channels

        brain_model = self.brain_model_config.build(
            n_in_channels=n_in_channels, n_outputs=n_hidden 
        )

        self._brain_module = self._init_module(brain_model)

        self._trainer = self._setup_trainer()
        self._trainer.fit(
            model=self._brain_module,
            train_dataloaders=train_loader,
            val_dataloaders=valid_loader,
            ckpt_path=self._brain_module.checkpoint_path,
        )

    def test(self, test_loader: DataLoader) -> None:
        self._trainer.test(self._brain_module, dataloaders=test_loader)

    @infra.apply
    def run(self):
        self._logger = (
            self.infra.wandb_config.build(
                save_dir=self.infra.folder,
                xp_config=self.model_dump(),
            )
            if self.infra.wandb_config
            else None
        )
        
        pl.seed_everything(self.seed, workers=True)

        loaders = self.data.build()
        self.fit(loaders["train"], loaders["val"])
        self.test(loaders["test"])

        return
