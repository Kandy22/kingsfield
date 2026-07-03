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
from .defaults import PROJECT_NAME, SAVEDIR, default_config  # type: ignore

GRID_NAME = "hp_search"

update = {
    "infra": {
        "cluster": "auto",
        "folder": SAVEDIR,
        "slurm_partition": "learnfair",
        "timeout_min": 60,
        "gpus_per_node": 1,
        "cpus_per_task": 10,  # Also used for num_workers
        "job_name": PROJECT_NAME,
        "wandb_config": {
            "group": GRID_NAME,
        },
    },
    "patience": 15,
}

grid = {
    "brain_model_config.depth": [2, 4, 16],
    "n_epochs": [100, 0],  # n_epochs=0 for chance-level
    "optim.lr": [3e-4, 1e-3],
    "seed": [33, 87],
}


if __name__ == "__main__":
    updated_config = ConfDict(default_config)
    updated_config.update(update)

    out = run_grid(
        Experiment,
        GRID_NAME,
        updated_config,
        grid,  # type: ignore
        job_name_keys=["infra.wandb_config.name", "infra.job_name"],
        combinatorial=True,
        overwrite=True,
        dry_run=False,
        infra_mode="force",
    )
