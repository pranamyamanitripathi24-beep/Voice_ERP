"""Offline speech-to-text using Vosk."""

import os
from pathlib import Path


class STTEngine:
    def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError


def preprocess_audio(input_path: str) -> str:
    """Converts any input audio to 16kHz mono WAV — the format Vosk expects.

    This step is the single most common cause of "my voice isn't being
    recognized accurately" in projects like this. A laptop or phone mic
    usually records at 44.1kHz or 48kHz in stereo; feeding that straight
    into an STT engine doesn't crash, it just silently produces much
    worse transcriptions — there's no error message telling you why
    accuracy is bad, it just is. Converting explicitly removes that whole
    failure class.

    Requires ffmpeg installed and on PATH (see README "Improving voice
    accuracy" section for install instructions per OS).
    """
    import subprocess
    import tempfile

    out_path = tempfile.NamedTemporaryFile(delete=False, suffix="_16k_mono.wav").name
    cmd = ["ffmpeg", "-y", "-i", input_path, "-ac", "1", "-ar", "16000", out_path]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Audio preprocessing failed — is ffmpeg installed and on PATH? "
            f"ffmpeg error: {result.stderr.decode(errors='ignore')[-500:]}"
        )
    return out_path


class VoskSTT(STTEngine):
    """Offline, lightweight STT. `pip install vosk` and download a model from
    https://alphacephei.com/vosk/models (e.g. vosk-model-small-en-us-0.15)."""

    def __init__(self, model_path: str):
        from vosk import Model, KaldiRecognizer
        import wave
        self._wave = wave
        self.model = Model(model_path)
        self._KaldiRecognizer = KaldiRecognizer

    def transcribe(self, audio_path: str) -> str:
        import json
        wf = self._wave.open(audio_path, "rb")
        rec = self._KaldiRecognizer(self.model, wf.getframerate())
        text_parts = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                text_parts.append(json.loads(rec.Result()).get("text", ""))
        text_parts.append(json.loads(rec.FinalResult()).get("text", ""))
        return " ".join(p for p in text_parts if p).strip()


def get_engine(model_path: str | None = None) -> STTEngine:
    """Load Vosk from VOSK_MODEL_PATH or the bundled-model directory."""
    model_path = model_path or os.environ.get("VOSK_MODEL_PATH")
    if not model_path:
        model_path = str(
            Path(__file__).resolve().parent.parent
            / "models"
            / "vosk-model-small-en-us-0.15"
        )
    return VoskSTT(model_path=model_path)
