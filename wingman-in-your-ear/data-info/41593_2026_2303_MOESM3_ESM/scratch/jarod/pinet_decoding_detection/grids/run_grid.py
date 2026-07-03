# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Grid over different configurations of stimulus classification experiment.
"""

from neuralset.infra import ConfDict
from neuraltrain.utils import run_grid

from ..main import Experiment  # type: ignore
from .defaults import SAVEDIR, default_config  # type: ignore

GRID_NAME = "101_TYPING_REVIEWS_DETECTION_EEG"
PROJECT_NAME = "pinet_decoding"

NUM_CLASSES = 29

update = {
    "infra": {
        "cluster": "auto",
        "folder": SAVEDIR,
        "slurm_partition": "learnfair",
        "timeout_min": 48*60,
        "gpus_per_node": 1,
        "cpus_per_task": 10,  # Also used for num_workers
        "slurm_constraint": "volta32gb",
        "job_name": PROJECT_NAME,
        "wandb_config": {
            "group": GRID_NAME,
        },
    },
    "patience": 12,
    "n_epochs": 100,
    "data.neuro.name": "Eeg",
    "data.study.name": "Pinet2024Eeg",
    "data.study.query": None

}

grid = {
    "data.splitting_seed": [0, 1, 5],
    "optimizer.scheduler.kwargs.max_lr": [1e-3, 5e-3, 5e-4],
}

if __name__ == "__main__":
    updated_config = ConfDict(default_config)
    updated_config.update(update)

    out = run_grid(
        Experiment,
        GRID_NAME,
        updated_config,
        grid,
        job_name_keys=["infra.wandb_config.name", "infra.job_name"],    
        combinatorial=True,
        overwrite=True,
        dry_run=False,
    )
