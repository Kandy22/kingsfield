# Brain2Qwerty — Typing Decoding from MEG/EEG

This repository contains the code for **Brain2Qwerty**, a pipeline that decodes typed text from non-invasive brain recordings (MEG and EEG). The system trains a convolutional neural network followed by a Transformer sequence model, then refines predictions with an N-gram language model.

## Repository Structure

```
neuralset/              Data loading and feature extraction library
neuraltrain/            Model architectures, losses, metrics, optimizers
scratch/jarod/
├── pinet_decoding/           Main decoding pipeline (Conv+Trans → character prediction)
│   ├── main.py               Experiment definition and training loop
│   ├── pl_module.py          PyTorch Lightning module
│   ├── callbacks.py          Training callbacks (logging, prediction decoding)
│   ├── linear_model_CV.py    Ridge classifier baseline (cross-validated)
│   ├── grids/
│   │   ├── defaults.py       Default experiment config (smoke-test entry point)
│   │   ├── run_grid.py       Grid-search launcher for sweeps
│   │   └── utils.py          Shared utilities (Levenshtein, keyboard layout, etc.)
│   └── ...
├── pinet_decoding_detection/ Keystroke detection pipeline (event onset detection)
│   ├── main.py               Detection experiment
│   ├── linear_model.py       Ridge classifier baseline
│   ├── compute_cache.py      MEG data caching
│   ├── compute_cache_eeg.py  EEG data caching
│   └── grids/                Config and grid search
└── scripts/                  Post-training result extraction and analysis
    ├── extract_predictions.py  Reconstruct sentences from callback logs → CSV
    └── ngram_decoding.py       Apply N-gram LM beam search to model predictions
```

## Installation

**Requirements:** Python 3.10+, CUDA-capable GPU.

```bash
conda create -n brain2qwerty python=3.10 -y
conda activate brain2qwerty

# Install packages (editable mode)
pip install -e neuralset
pip install -e neuraltrain

# For N-gram decoding
pip install kenlm Levenshtein
```

## Environment Configuration

All data paths are configurable via environment variables. Set them before running any script:

```bash
export BRAINAI_ROOT="$HOME/brainai"            # Root directory
export BRAINAI_DATA_ROOT="$BRAINAI_ROOT/data"  # Data files (CSVs, .npy, etc.)
export BRAINAI_CACHE="$BRAINAI_ROOT/cache"     # Preprocessed feature cache
export BRAINAI_RESULTS="$BRAINAI_ROOT/results" # Training results and checkpoints
export BRAINAI_STUDIES_PATH="$BRAINAI_DATA_ROOT/studies"  # Raw study data
```

### Expected Data Layout

```
$BRAINAI_ROOT/
├── data/
│   ├── studies/               Raw MEG/EEG recordings (neuralset format)
│   │   └── Pinet2024Meg/      MEG study data
│   ├── lm_arpa_files/         N-gram language model (.arpa)
│   │   └── news_9gram.arpa
│   └── ...
├── cache/                     Auto-generated preprocessed features
└── results/                   Training outputs and checkpoints
```

## Training

### Quick Debug Run (Smoke Test)

Verify the pipeline works end-to-end on a single subject with 2 epochs:

```bash
cd scratch/jarod
python -m pinet_decoding.grids.defaults
```

This uses the default configuration in `grids/defaults.py` which trains on one subject (`S1`) for 2 epochs with progress bars enabled. **Success criteria:** training launches without errors, loss decreases, no NaN values.

### Full Training

For a full training run on all subjects, use the grid launcher:

```bash
cd scratch/jarod
python -m pinet_decoding.grids.run_grid
```

The grid launcher submits jobs via SLURM (set `"cluster": "auto"` in the config) or runs locally (`"cluster": None`). It sweeps over splitting seeds and sensor ablation configurations.

To customize training, edit `pinet_decoding/grids/run_grid.py`:

- **Single subject:** set `"data.study.query": "subject.isin(['Pinet2024Meg/S1'])"`
- **All subjects:** set `"data.study.query": None`
- **Number of epochs:** modify `"n_epochs"`
- **Learning rate:** modify `"lr"` or `"optimizer.optimizer.lr"`

### Keystroke Detection Model

```bash
cd scratch/jarod
python -m pinet_decoding_detection.grids.defaults    # debug
python -m pinet_decoding_detection.grids.run_grid    # full grid
```

### Linear Baseline

```bash
cd scratch/jarod
python pinet_decoding/linear_model_CV.py
```

## Checkpoints

### Saving

Checkpoints are saved automatically when `"save_checkpoints": True` in the config. Two files are saved in `$BRAINAI_RESULTS/pinet_decoding/<job_name>/`:

- `last.ckpt` — latest epoch
- `best.ckpt` — best validation CER

To enable saving, set in `run_grid.py`:

```python
"save_checkpoints": True,
```

### Loading / Resuming

If a `last.ckpt` exists in the experiment folder and `"load_checkpoint": True`, training resumes from that checkpoint automatically. To use a specific checkpoint for inference:

```python
from pinet_decoding.pl_module import BrainModule

module = BrainModule.load_from_checkpoint("path/to/best.ckpt")
module.eval()
```

## Result Extraction and Analysis

All analyses reported in the paper are derived from two post-training processing steps, provided as standalone scripts in `scripts/`.

### Step 1: Extract structured predictions

During training, the `LogPreds` callback (see `pinet_decoding/callbacks.py`) saves per-sentence predictions as JSON files in the experiment's `callbacks/` directory. The extraction script reads these JSON files, reconstructs the predicted and typed sentences from class indices, and computes per-sentence CER and WER for each subject:

```bash
python scripts/extract_predictions.py \
    --input $BRAINAI_RESULTS/pinet_decoding/<experiment>/callbacks \
    --output predictions.csv
```

This produces a CSV with columns: `Subject`, `Sentence_UID`, `True Sentences`, `Typed Sentences`, `Model Predictions`, `Logits`, `CER`, `WER`.

### Step 2: Apply N-gram language model

The second script applies character-level beam search with a KenLM N-gram model to refine the raw neural predictions:

```bash
python scripts/ngram_decoding.py \
    --input predictions.csv \
    --lm $BRAINAI_DATA_ROOT/lm_arpa_files/news_9gram.arpa \
    --output predictions_with_lm.csv
```

This adds columns: `LM Predictions`, `CER_LM`, `WER_LM`.

The resulting CSV contains all the per-sentence, per-subject data needed to reproduce any analysis or figure in the paper (performance comparisons, error rate breakdowns, lexical analyses, etc.).

### Approximate Timing

| Stage | Hardware | Duration |
|-------|----------|----------|
| Data caching (per subject, MEG) | CPU | ~5–10 min |
| Training 1 subject, 100 epochs (Conv+Trans) | 1× V100 32GB | ~2–4 hours |
| Training all 19 subjects, 100 epochs | 1× V100 32GB | ~16–20 hours |
| N-gram post-processing (all subjects) | CPU | ~5–15 min |
| Linear baseline (all subjects) | CPU | ~10–30 min |

## License

See the LICENSE file in the root directory of this source tree.
