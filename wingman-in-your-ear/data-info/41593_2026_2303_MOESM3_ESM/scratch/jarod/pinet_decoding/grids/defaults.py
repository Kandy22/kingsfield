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


BUTTON_MAPPING = {
    's': 0, 'o': 1, 't': 2, 'e': 3, 'n': 4, 'c': 5, 'i': 6, 'a': 7, '<space>': 8, 
    'd': 9, 'l': 10, 'r': 11, 'b': 12, '<special>': 13, 'z': 14, 'v': 15, 'f': 16, 
    'm': 17, 'u': 18, 'h': 19, 'p': 20, 'g': 21, 'q': 22, 'w': 23, 'x': 24, 'y': 25, 
    'j': 26, 'ý': 13, '\x14': 13, 'k': 27, 'ü': 13, 'û': 13, '£': 13, '¤': 13, 
    '<number>': 28, '-': 13, '¿':13, '\u0060':13, '`':13
}
NUM_CLASSES = len(set(BUTTON_MAPPING.values()))

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
            "copied": ["neuralset", "neuraltrain", "pinet_decoding"],
            "includes": ["*.py", "*.txt"]
        },
    },
    "data": {
        "study": {
            "name": "Pinet2024Meg",
            "infra": {'folder': CACHE},
            "path": os.environ.get("BRAINAI_STUDIES_PATH", os.path.join(_DATA_ROOT, "studies")),
            "query": "subject.isin(['Pinet2024Meg/S1'])",

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
            "name": "LabelEncoder", 
            "aggregation": "trigger",
            "predefined_mapping": BUTTON_MAPPING,
            "event_types": ["Button", "DetectedButton"],
            "event_field": "button",
            "return_one_hot":False,
        },
        
        "valid_size": 0.2,
        "test_size": 0.2,
        "start": -0.2,
        "num_classes": NUM_CLASSES,
        "duration": 0.5,
        "batch_size": 128,
        "val_batch_size": 2048,
        "test_batch_size": 2048,
        "num_workers": 0,
        "splitting_seed": 1,
        "splitting_ratios": (0.8, 0.1, 0.1),
        # # Subject Study
        # 'one_subject_study': False,
        # 'subject_study_id': None,ß
        # 'proportion_data_amount': None
        
        # Scaling Law Study
        "timeline_study": False,
        "n_samples":1,
        "sentence_study": False,
        "n_sentences":1,
        "subject_study": False,
        "n_subjects":2,

        # Second step in 2-step model
        "second_step": False,

    },

    # "brain_model_config": {
    #     "name": "EEGNet",
    #     "depth": 6,
    #     "dropout": 0.3 
    # },

    "brain_model_config": {
        "name": "SimpleConvTimeAgg",
        "time_agg_out": "att",
        "dropout_input": 0.2,
        "conv_dropout": 0.5,
        "hidden": 2048,
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

    # "brain_model_config": {
    #     "name": "LinearModel",
    #     "subject_layers_config": {"n_subjects": 50},
    # },

    "transformer_config": {
        "name": "TransformerEncoder",
        "alibi_pos_bias": True, # Positional Encoding 
        "depth": 4,  # 8 for EEG
        "heads": 2,  # 4 for EEG
    },

    "metrics": [
        {
            "log_name": "acc_macro",
            "name": "Accuracy",
            "kwargs": {
                "task": "multiclass",
                "average": "macro",
                "num_classes": NUM_CLASSES,
            },
        },
        {
            "log_name": "acc_weighted",
            "name": "Accuracy",
            "kwargs": {
                "task": "multiclass",
                "average": "weighted",
                "num_classes": NUM_CLASSES,
            },
        },
        {
            "log_name": "CER",
            "name": "CharacterErrorRateMetricBaseline",
        },
    ],
    "use_transformer": True,
    "intermediary_layer_study": False,
    "loss": {"name": "CrossEntropyLoss", "kwargs": {}},
    "save_checkpoints": False,
    "load_checkpoint": False,
    "n_epochs": 2,
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
                "lr": 1e-4,
                "kwargs": {
                    "weight_decay": 0.0001,
                },
            },
            "scheduler": {
                "name": "OneCycleLR",
                "kwargs": {
                    "max_lr": 1e-4,
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
