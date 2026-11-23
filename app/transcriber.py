"""Motores de transcricao: faster-whisper (local, gratis) ou OpenAI (nuvem)."""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from abc import ABC, abstractmethod

LOCAL_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
OPENAI_MODELS = ["whisper-1", "gpt-4o-mini-transcribe", "gpt-4o-transcribe"]


def decode_audio(path: str):
    """Decodifica qualquer formato (opus, m4a, amr...) para float32 mono 16 kHz via ffmpeg."""
    import numpy as np

    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "f32le",
         "-ac", "1", "-ar", "16000", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "ffmpeg falhou")
    return np.frombuffer(proc.stdout, dtype=np.float32)


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, path: str, language: str | None) -> str: ...


class LocalWhisper(Transcriber):
    _models: dict[str, object] = {}
    _lock = threading.Lock()

    def __init__(self, model: str):
        self.model_name = model

    def _get_model(self):
        with self._lock:
            if self.model_name not in self._models:
                from faster_whisper import WhisperModel

                self._models[self.model_name] = WhisperModel(
                    self.model_name,
                    device=os.getenv("WHISPER_DEVICE", "auto"),
                    compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
                )
            return self._models[self.model_name]

    def transcribe(self, path: str, language: str | None) -> str:
        model = self._get_model()
        segments, _info = model.transcribe(
            decode_audio(path),
            language=language or None,
            vad_filter=True,
            beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
        )
        return " ".join(s.text.strip() for s in segments).strip()


class OpenAITranscriber(Transcriber):
    def __init__(self, model: str):
        from openai import OpenAI

        self.model = model
        self.client = OpenAI()

    def transcribe(self, path: str, language: str | None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = os.path.join(tmp, "audio.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1",
                 "-ar", "16000", "-b:a", "32k", mp3],
                check=True,
            )
            with open(mp3, "rb") as f:
                kwargs = {"model": self.model, "file": f}
                if language:
                    kwargs["language"] = language
                res = self.client.audio.transcriptions.create(**kwargs)
        return (res.text or "").strip()


def available_engines() -> dict:
    return {
        "local": {"label": "Local (faster-whisper, gratis, offline)", "models": LOCAL_MODELS,
                  "default_model": os.getenv("WHISPER_MODEL", "small"), "available": True},
        "openai": {"label": "OpenAI (nuvem, mais rapido, pago)", "models": OPENAI_MODELS,
                   "default_model": "whisper-1",
                   "available": bool(os.getenv("OPENAI_API_KEY"))},
    }


def make_transcriber(engine: str, model: str) -> Transcriber:
    if engine == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY nao configurada.")
        return OpenAITranscriber(model)
    if engine == "local":
        return LocalWhisper(model)
    raise ValueError(f"Motor desconhecido: {engine}")
