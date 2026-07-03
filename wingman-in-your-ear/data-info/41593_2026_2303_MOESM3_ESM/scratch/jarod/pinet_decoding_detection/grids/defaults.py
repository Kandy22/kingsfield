# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Default configuration dictionary for project template experiment on Pinet2024Meg dataset.
"""

import os

PROJECT_NAME = "pinet_decoding"
_BRAINAI_ROOT = os.environ.get("BRAINAI_ROOT", os.path.expanduser("~/brainai"))
_DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.join(_BRAINAI_ROOT, "data"))
CACHE = os.environ.get("BRAINAI_CACHE", os.path.join(_BRAINAI_ROOT, "cache", PROJECT_NAME))
SAVEDIR = os.environ.get("BRAINAI_RESULTS", os.path.join(_BRAINAI_ROOT, "results", PROJECT_NAME))

default_config = {
    "infra": {
        "cluster": None,  # Run example locally
        "folder": SAVEDIR,
        "gpus_per_node": 1,
        "cpus_per_task": 10,
        "slurm_constraint": "volta32gb",
        "wandb_config": {
            "log_model": False,
            "project": PROJECT_NAME,
            "group": "default",
            "host": "https://fairwandb.org/",
        },
        "workdir": {
            "copied": ["neuralset", "neuraltrain", "pinet_decoding_detection"],
            "includes": ["*.py", "*.txt"]
        },
    },
    "data": {
        "study": {
            "name": "Pinet2024Meg",
            "infra": {'folder': CACHE},
            "path": os.environ.get("BRAINAI_STUDIES_PATH", os.path.join(_DATA_ROOT, "studies")),
            "query": "subject.isin(['Pinet2024Meg/S1', 'Pinet2024Meg/S2', 'Pinet2024Meg/S3', 'Pinet2024Meg/S4'])",

        },
        "neuro": {
            "name": "Meg",
            "frequency": 50,
            "sensor_ablation": None,
            "filter": (0.1, 20.0),
            "baseline": (0.0, 0.2),
            "apply_proj": False,
            "clamp": 5,
            "scaler": "RobustScaler",
            "infra": {
                "folder": CACHE,
                "cluster": None,
            },
        },
        "feature": {
            "name": "EventDetector", 
            "mode": "flat_confidence",
            "aggregation": "sum",
            "event_types": "Button",
            "frequency": 50.0,
        },
        "valid_size": 0.2,
        "test_size": 0.2,
        "start": 0,
        "duration": None,
        "batch_size": 512,
        "val_batch_size": 512,
        "test_batch_size": 512,
        "splitting_seed": 1,
        "splitting_ratios": (0.8, 0.1, 0.1),
        
    },

    "brain_model_config": {
        "name": "SimpleConv",
        "dropout_input": 0.2,
        "conv_dropout": 0.5,
        "hidden": 512,
        "batch_norm": True,
        "depth": 8,
        "dilation_period": 3,
        "kernel_size": 3,
        "relu_leakiness": 0.01,
        "initial_linear": 512,
        "gelu": True,
        "skip": True,
        "scale": 0.1,
        "subject_layers_config": {},
        "merger_config": {
            "n_virtual_channels":270,
            "fourier_emb_config": {
                "n_freqs":None,
                "total_dim":2048,
                "n_dims":2,
            },
            "dropout":0.2,
            "usage_penalty":1.0,
            "per_subject": True,
            "embed_ref":False,
        }

    },

    "metrics": [
        {
            "log_name": "f1",
            "name": "BinaryF1Score",
            "kwargs": {
                "threshold": 0.5
            },
        },
        {
            "log_name": "recall",
            "name": "BinaryRecall",
            "kwargs": {
                "threshold": 0.5
            },
        },
        {
            "log_name": "precision",
            "name": "BinaryPrecision",
            "kwargs": {
                "threshold": 0.5
            },
        },
    ],

    "use_transformer": False,
    "intermediary_layer_study": False,
    
    # OVERWRITTEN IN PL_MODULE
    "loss": {"name": "BCEWithLogitsLoss", "kwargs": {}},
    
    
    "save_checkpoints": False,
    "load_checkpoint": False,
    "n_epochs": 1,
    "limit_train_batches": None,
    "transformer_start_epoch": 0,
    "patience": 80,
    "use_scheduler": True,
    "channels_study":False,
    "channels_peripheral":False,
    "channels_central":False,
    "n_channels":306,
    "grad_max_norm": 5.0,
    "strategy": "auto",
    "enable_progress_bar": True,
    "log_every_n_steps": 5,
    "fast_dev_run": False,
    "seed": 33,

    # Older version
    "scheduler_type": "ReduceLROnPlateau", 
    "weight_decay": 0.0001,
    "lr": 1e-4, 


    "optimizer": {
            "optimizer": {
                "name": "AdamW",
                "lr": 1e-3,
                "kwargs": {
                    "weight_decay": 0.0001,
                },
            },
            "scheduler": {
                "name": "OneCycleLR",
                "kwargs": {
                    "max_lr": 1e-3,
                    "pct_start": 0.1,
                    "total_steps":100,
                },
            },
        },
}


if __name__ == "__main__":
    # The following can be used for local debugging/quick tests.

    from ..main import Experiment

    exp = Experiment(
        **default_config,
    )

    exp.infra.clear_job()
    out = exp.run()
    print(out)
