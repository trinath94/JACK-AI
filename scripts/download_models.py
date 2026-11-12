"""Download Whisper models into a Hugging Face cache directory (CI and offline setups).

Usage: uv run --project services/api python scripts/download_models.py <dir> [model ...]
Default models: tiny.en small.en
"""

from __future__ import annotations

import sys

from huggingface_hub import snapshot_download

from jack_api.voice.asr import MODELS


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    root, names = sys.argv[1], sys.argv[2:] or ["tiny.en", "small.en"]
    for name in names:
        path = snapshot_download(MODELS[name].repo, cache_dir=root,
                                 allow_patterns=["config.json", "model.bin", "tokenizer.json",
                                                 "vocabulary.*", "preprocessor_config.json"])
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
