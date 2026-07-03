
import os

import neuralset as ns
from neuralset.data import StudyLoader

if __name__ == "__main__":
    _brainai_root = os.environ.get("BRAINAI_ROOT", os.path.expanduser("~/brainai"))
    _data_root = os.environ.get("BRAINAI_DATA_ROOT", os.path.join(_brainai_root, "data"))
    cache = os.environ.get("BRAINAI_CACHE", os.path.join(_brainai_root, "cache", "pinet_decoding"))
    
    default_config = {
        "study": {
            "name": "Pinet2024Eeg",
            'path': os.environ.get("BRAINAI_STUDIES_PATH", os.path.join(_data_root, "studies")),
            "query": None,
            "infra": {"folder": cache, "mode": "cached"},
        },
        
        "neuro": {
            "name": "Eeg",
            "frequency": 50.0,
            "filter": (0.1, 20),
            "baseline": (0.0, 0.2),
            "scaler": "RobustScaler",
            "clamp": 5,
            "infra": {
                "keep_in_ram": True,
                "folder": cache,
                "cluster": None,
            },
        },
    }

    study = StudyLoader(**default_config['study'])
    events = study.build()
    neuro = ns.features.Eeg(**default_config['neuro'])
    neuro.prepare(events)
    print(f"[INFO] Done.")