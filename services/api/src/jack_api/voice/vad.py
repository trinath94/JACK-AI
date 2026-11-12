"""Voice activity detection.

``SileroVad`` streams the Silero VAD v6 model (MIT) bundled with faster-whisper through
onnxruntime: 512-sample frames plus 64 samples of context, recurrent state carried between
frames. About 1 ms of CPU per 32 ms frame.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import numpy as np

CONTEXT = 64


class Vad(Protocol):
    def prob(self, frame: np.ndarray) -> float: ...
    def reset(self) -> None: ...


def silero_model_path() -> str:
    import faster_whisper

    return os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")


class SileroVad:
    def __init__(self, path: str | None = None) -> None:
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._session: Any = onnxruntime.InferenceSession(
            path or silero_model_path(), providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((CONTEXT,), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self._context, frame.astype(np.float32)])[None, :]
        out, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = frame[-CONTEXT:].astype(np.float32)
        return float(np.asarray(out).reshape(-1)[0])
