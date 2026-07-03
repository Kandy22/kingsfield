# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import typing as tp

import pandas as pd
import tqdm


def add_sentences(
    events: pd.DataFrame,
    ratios: tp.Tuple[float, float, float] = (0.8, 0.1, 0.1),
    column_to_group: str = "sequence_id",
) -> pd.DataFrame:
    """
    Add sentence-level information to the events DataFrame based on the sequence_id column.
    """

    assert column_to_group in events.columns
    assert "Sentence" not in events.type.unique()

    if "timeline" in events.columns and len(events.timeline.unique()) > 1:
        # apply to each timeline
        timelines = []
        for _, df in tqdm.tqdm(events.groupby("timeline"), "Adding sentences"):
            df = add_sentences(df, ratios, column_to_group)
            timelines.append(df)
        return pd.concat(timelines)
    events["stop"] = events.start + events.duration

    words = events.query('type=="Word"')
    assert all(words.start.diff().dropna() >= 0)  # type: ignore

    # Add sentence-level information
    words = events.query('type=="Word"')
    sentences = []
    for _, sent in words.groupby(column_to_group, sort=False):
        # Find all events within the sentence
        duration = sent.stop.max() - sent.start.min() + 1e-8

        sentence = " ".join(sent.text)
        events.loc[sent.index, "sentence"] = sentence

        # Add Sentence event
        to_add = sent.iloc[0].to_dict()
        to_add["type"] = "Sentence"
        to_add["text"] = " ".join(sent.text)
        to_add["start"] = sent.start.min() - 1e-8
        to_add["duration"] = duration
        to_add["stop"] = sent.stop.max()
        sentences.append(to_add)

    events = pd.concat([events, pd.DataFrame(sentences)], ignore_index=True)
    events = events.sort_values("start")
    events = events.reset_index(drop=True)

    return events
