# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Quick test run on reduced data and number of epochs for CI.
"""

from exca import ConfDict

import neuralset as ns

from ..main import Experiment  # type: ignore
from .defaults import default_config  # type: ignore

update = {
    "infra.cluster": None,
    # use same folder as in neuralset tests to share cache:
    "data.study.path": ns.CACHE_FOLDER,
    "data.study.query": "timeline_index < 1",
    "accelerator": "cpu",
    "fast_dev_run": True,
    "infra.wandb_config": None,
}


def test_run(config: dict) -> None:
    task = Experiment(**config)
    task.infra.clear_job()
    trainer = task.run()
    metrics = trainer.logged_metrics.values()
    assert all(isinstance(metric.item(), float) for metric in metrics)


if __name__ == "__main__":
    updated_config = ConfDict(default_config)
    updated_config.update(update)
    test_run(updated_config)
