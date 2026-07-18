from __future__ import annotations

"""
Step 1d -- input-quality retrain (spec-hinglish-diagnostic-sweep.md). Retrains
the Step 1a WINNING config (LoRA r=8, lr=2e-4, 4 epochs) on the vocab-presence-
cleaned dataset (clean_input_quality.py -- corpus_pmi pairs restricted to
anchor+neighbor both already real production-vocab words, 669/888 pairs vs
756/1028 uncleaned) and compares against the winner trained on uncleaned data
(cap_lora_r8_lr2e-4, already logged) to isolate whether transliteration noise
was suppressing the win further.

Run: uv run python -m evals.finetune.step1d_input_quality_retrain
"""

import json
from pathlib import Path

from evals.finetune.run_sweep import _load_baseline_records, run_one
from evals.finetune.step1b_objective_sweep import WINNER_KWARGS
from evals.finetune.train_lib import TrainConfig

DATA_DIR = Path(__file__).parent / "data"


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


if __name__ == "__main__":
    mnrl = _load_jsonl(DATA_DIR / "train_mnrl_pairs_cleaned.jsonl")
    graded = _load_jsonl(DATA_DIR / "train_graded_pairs_cleaned.jsonl")
    cfg = TrainConfig(
        name="cap_lora_r8_lr2e-4_cleaned_input",
        mnrl_records=mnrl,
        graded_records=graded,
        **WINNER_KWARGS,
    )
    baseline_dim1, baseline_dim2 = _load_baseline_records()
    record = run_one(cfg, baseline_dim1, baseline_dim2)
    print(json.dumps({k: v for k, v in record.items() if not isinstance(v, dict)}, indent=2))
    print(f"dim1_test={record['dim1_test_spearman']:.4f} (uncleaned winner was 0.6339)")
