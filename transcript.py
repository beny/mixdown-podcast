"""Přepíše mluvený úvod mixu (česky) pomocí faster-whisper.

Úvod bývá sponzorský/informační blok před první skladbou — přepisuje se
jen prvních INTRO_SECONDS mixu, ne celý díl.

Použití jako modul:
    text = transcribe_intro("mix.mp3")
"""

import subprocess
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

INTRO_SECONDS = 120
MODEL_SIZE = "medium"
INITIAL_PROMPT = "Mix DOWN, Alešem Konopkou, radiocolor.cz"

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe_intro(mp3_path: str, seconds: float = INTRO_SECONDS) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        wav = str(Path(tmp) / "intro.wav")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-t", str(seconds), "-i", mp3_path,
             "-ac", "1", "-ar", "16000", wav],
            capture_output=True, check=True,
        )
        segments, _info = _get_model().transcribe(
            wav, language="cs", vad_filter=True, initial_prompt=INITIAL_PROMPT)
        return " ".join(s.text.strip() for s in segments).strip()
