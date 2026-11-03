"""Download the Hugging Face models the generator tests load, and fail if any has drifted.

The generator loads these models by name with no revision (config.MODELS,
eval_model.OFF_THE_SHELF_MODEL), so a test run silently picks up whatever the
model's `main` branch points to. CI instead resolves `main` once here, asserts
it is the pinned commit, and then runs pytest with HF_HUB_OFFLINE=1, so every
model load in the suite resolves to exactly the pinned snapshot in the cache.

If upstream moves `main`, this step fails with the new SHA: re-pin deliberately
(and bump the actions/cache key in unit-tests.yml) rather than test against an
unreviewed model.
"""

from __future__ import annotations

import sys

from huggingface_hub import snapshot_download

PINS: dict[str, str] = {
    # en model (config.MODELS["en"])
    "sentence-transformers/all-MiniLM-L6-v2": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    # hi-en model (config.MODELS["hi-en"])
    "gauravgandhi2411/hinglish-relatedness-sbert": "4b06ad914005cf93ad6a99878566c00a5a0af47b",
    # LoRA base model for test_train_lib_lora_best_checkpoint (eval_model.OFF_THE_SHELF_MODEL)
    "l3cube-pune/indic-sentence-bert-nli": "aab1d6a0ace569c670f54173e1b0f0bb607f13c8",
}

# Export formats sentence-transformers never loads on CPU torch; skipping them
# keeps the cache small (all-MiniLM-L6-v2 alone ships ONNX/OpenVINO/TF/Flax copies).
IGNORE = ["onnx/*", "openvino/*", "*.onnx", "*.h5", "*.msgpack", "*.ot", "*.tflite"]


def main() -> int:
    drift = []
    for repo_id, pinned in PINS.items():
        path = snapshot_download(repo_id, revision="main", ignore_patterns=IGNORE)
        resolved = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        status = "ok" if resolved == pinned else "DRIFT"
        print(f"{status} {repo_id} main={resolved} pinned={pinned}")
        if resolved != pinned:
            drift.append(repo_id)
    if drift:
        print(f"::error::model revision drift: {', '.join(drift)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
