# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import random
import typing as tp
from collections import Counter
from dataclasses import dataclass
from warnings import warn

import numpy as np
import pandas as pd
import pydantic

from . import events as event_module
from .events import EventTypesHelper
from .features.base import BaseStatic


@dataclass
class DeterministicSplitter:
    ratios: dict[str, float]
    seed: float = 0.0

    def __post_init__(self) -> None:
        # check that the spliting ratios is valid
        assert all(ratio > 0 for ratio in self.ratios.values())
        assert np.allclose(
            sum(self.ratios.values()), 1.0
        ), f"the sum of ratios must be equal to 1. got {self.ratios}"

    def __call__(self, uid: str) -> str:
        hashed = int(hashlib.sha256(uid.encode()).hexdigest(), 16)
        rng = random.Random(hashed + self.seed)
        score = rng.random()

        cdf = np.cumsum(list(self.ratios.values()))
        names = list(self.ratios.keys())
        # associate a split to this deterministc hash
        for idx, cdf_val in enumerate(cdf):
            if score < cdf_val:
                return names[idx]
        raise ValueError


def chunk_events(
    events: pd.DataFrame,
    event_type_to_chunk: tp.Literal["Sound", "Video"],
    event_type_to_use: str | None = None,
    min_duration: float | None = None,
    max_duration: float = np.inf,
):
    """
    Split events into smaller chunks.
    If event_type_to_use is None, the events are chunked into chunks of max_duration.
    If event_type_to_use is not None, the events are chunked based on the train/val/test splits of the event_type_to_use, ensuring that each chunk has duration between min_duration and max_duration.
    """

    added_events: list[tp.Dict] = []
    dropped_rows: list[int] = []
    ns_event_type_to_chunk = getattr(event_module, event_type_to_chunk)
    assert hasattr(
        ns_event_type_to_chunk, "_split"
    ), f"Event type {event_type_to_chunk} is not splittable"
    if event_type_to_use is not None:
        assert "split" in events.columns, "Events must have a split column"

    for _, df in events.groupby("timeline"):
        df.sort_values("start", inplace=True)
        if event_type_to_use is None:  # chunk based on max_duration
            timepoints: list[float] = np.arange(  # type: ignore
                df.start.min(), df.stop.max(), max_duration
            ).tolist()
            if min_duration is not None:
                if df.stop.max() - timepoints[-1] < min_duration:
                    timepoints = timepoints[:-1]
        else:  # chunk based on train/test split of the event_type_to_use
            timepoints = []
            events_to_use = df.loc[events.type == event_type_to_use].copy()
            previous = events_to_use.copy().shift(1)
            split_change = events_to_use.split.astype(str) != previous.split.astype(str)
            events_to_use["section"] = np.cumsum(split_change.values)  # type: ignore
            for _, section in events_to_use.groupby("section"):
                start, end = (
                    section.iloc[0].start,
                    section.iloc[-1].start + section.iloc[-1].duration,
                )
                timepoints.extend(np.arange(start, end, max_duration))

        events_to_chunk = df.loc[events.type == event_type_to_chunk]
        dropped_rows.extend(events_to_chunk.index)
        for row in events_to_chunk.itertuples():
            event_to_chunk = ns_event_type_to_chunk.from_dict(row)
            new_events = event_to_chunk._split([t - event_to_chunk.start for t in timepoints], min_duration)  # type: ignore
            for new_event in new_events:
                new_event_dict = new_event.to_dict()
                # add the columns which were removed by event.from_dict() except index
                for k, v in row._asdict().items():  # type: ignore
                    if k not in new_event_dict:
                        new_event_dict[k] = v
                added_events.append(new_event_dict)

    out_events = events.copy()
    out_events.drop(dropped_rows, inplace=True)
    out_events = pd.concat([out_events, pd.DataFrame(added_events)])
    out_events.reset_index(drop=True, inplace=True)
    return out_events


class SimilaritySplitter(pydantic.BaseModel):
    """A class used to split events based on similarity clustering of static features.
    The class uses agglomerative clustering on precomputed embeddings of the events
    to ensure that same and similar events remain in the same split to avoid data leaking.

    Parameters
    ----------
    feature : BaseStatic
        A static feature extraction model that defines the type of event
        and provides methods to extract embeddings from events.
    ratios : Dict[str, float]
        A dictionary defining the proportion of events for each split.
        The sum of all ratios must equal 1.
    threshold : float
        The threshold for the distance used in the agglomerative clustering.
        Events with a distance below this threshold are grouped into clusters.

    """

    feature: BaseStatic
    ratios: dict[str, float] = {"train": 0.5, "val": 0.25, "test": 0.25}
    threshold: float = 0.2

    def model_post_init(self, log__) -> None:
        super().model_post_init(log__)
        if any(ratio <= 0 for ratio in self.ratios.values()):
            raise ValueError("All ratios must be greater than 0. Got: {self.ratios}")

        total_ratio = sum(self.ratios.values())
        if not np.isclose(total_ratio, 1.0, atol=1e-8):
            msg = f"The sum of ratios must be equal to 1.0. Got: {total_ratio}"
            raise ValueError(msg)

    def _similarity_clustering(self, embeddings) -> list[int]:
        """Perform similarity-based clustering on the similarity matrix.

        Parameters
        ----------
        similarity_matrix: np.ndarray
            Precomputed cosine similarity matrix of dimension (number of events, number of events).


        Returns
        -------
        List[int]
            Clusters of indices.
        """

        from sklearn.cluster import AgglomerativeClustering
        from sklearn.metrics.pairwise import cosine_similarity

        similarity_matrix = cosine_similarity(embeddings)
        distance_matrix = 1 - similarity_matrix

        clustering = AgglomerativeClustering(
            n_clusters=None,
            metric="precomputed",
            distance_threshold=self.threshold,
            linkage="complete",  # uses maximum distances between all observations of the 2 sets
        )

        return [label.item() for label in clustering.fit_predict(distance_matrix)]

    def _cluster_assignment(self, clusters: list[int]) -> list[str]:
        """Assigns clusters to predefined splits (e.g., 'train', 'val', 'test') based on the
        ratios specified in `self.ratios`. Each cluster is assigned to a split such that
        the number of clusters in each split respects the specified ratio, and clusters are
        entirely allocated to a single split (no partial assignments).

        Parameters
        ----------
        clusters: list[int]
            A list of cluster IDs, where each cluster is represented by an integer,
            and the list contains the clusters to be assigned to splits.

        Returns
        -------
        list[str]
            A list of split labels ('train', 'val', 'test', etc.), corresponding
            to the same length as `clusters`, where each element indicates the split
            assignment for the corresponding cluster in the `clusters` input.
        """
        cluster_count = Counter(clusters)
        total_count = len(clusters)
        sorted_splits = sorted(self.ratios.items(), key=lambda x: x[1])
        split_sizes = {}
        cluster_split = {}

        # Split Assignment Strategy: littlest splits first, biggest split = remaining for no border effects
        remaining_count = total_count
        for split, ratio in sorted_splits[:-1]:
            split_sizes[split] = int(np.ceil(ratio * total_count))
            remaining_count -= int(np.ceil(ratio * total_count))
        largest_split = sorted_splits[-1][0]
        split_sizes[largest_split] = remaining_count

        # Take all indexes of one cluster and assign them to a split
        for key, count in cluster_count.items():
            for split, size in split_sizes.items():
                if size >= count:
                    cluster_split[key] = split
                    split_sizes[split] -= count
                    break

        # Handle the case where all examples are assigned to the same cluster
        if len(cluster_split) == 0:
            msg = "All examples are assigned to the same cluster. "
            msg += f"Try lowering the threshold value (currently {self.threshold}) to get more clusters."
            raise ValueError(msg)

        # Assert all splits have at least one cluster
        if not (set(cluster_split.values()) == set(self.ratios.keys())):
            msg = "Some splits have no clusters. Change the ratios or increase the number of examples."
            raise ValueError(msg)

        return [cluster_split[cluster] for cluster in clusters]

    def compute_clusters(self, events: pd.DataFrame) -> pd.DataFrame:
        """Filter events by the event types defined in the feature and compute cluster assigments."""
        self.feature.prepare(events)
        splitted_events = events[
            events["type"].isin(EventTypesHelper(self.feature.event_types).names)
        ].copy()

        embedding_list = []
        for _, row in splitted_events.iterrows():
            e = event_module.Event.from_dict(row.to_dict())
            embedding_list.append(self.feature.get_static(e))

        embeddings = np.stack([embd.numpy() for embd in embedding_list])
        clusters = self._similarity_clustering(embeddings)

        # Check for imbalanced clusters
        counts = pd.Series(clusters).value_counts().values
        if max(counts) / min(counts) >= 10.0:  # arbitrary threshold for imbalance
            msg = "The clusters are highly imbalanced. Try lowering the threshold value "
            msg += f"(currently {self.threshold}) to get more clusters."
            warn(msg)

        splitted_events["cluster_id"] = clusters
        return splitted_events

    def __call__(self, events: pd.DataFrame) -> pd.DataFrame:
        """Splits a given DataFrame based on similarity clustering.

        Parameters
        ----------
        events: pd.DataFrame
            A DataFrame containing event data, with each row representing
            a single event and columns representing the event's attributes.

        Returns
        -------
        pd.DataFrame
            A copy of the input DataFrame with an additional 'split' column, which
            indicates the assigned split for each event.

        """
        splitted_events = self.compute_clusters(events)
        cluster_assignment = self._cluster_assignment(
            splitted_events["cluster_id"].tolist()
        )

        out_events = events.copy()
        out_events["split"] = ""
        out_events.loc[splitted_events.index, "split"] = cluster_assignment

        return out_events
