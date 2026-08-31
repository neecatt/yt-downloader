"""Deployable Modal application for link-to-transcript jobs.

Deploy with:

    modal deploy backend/modal_transcriber.py

The Railway bot invokes the deployed ``transcribe`` Function through Modal's
authenticated SDK lookup. This file is intentionally separate from the bot's
runtime image.
"""

from __future__ import annotations

import os
import logging
import tempfile
import time
from pathlib import Path

import modal


LOG = logging.getLogger("modal_transcriber")


def _log_level() -> int:
    candidate = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, candidate, logging.INFO)

APP_NAME = os.getenv("MODAL_APP_NAME", "yt-downloader-transcriber")
MODEL_NAME = os.getenv("WHISPER_MODEL", "small")
SUMMARY_MODEL_NAME = os.getenv("SUMMARY_MODEL", "Qwen/Qwen2.5-3B-Instruct")
SUMMARY_MAX_CHARS = max(4000, int(os.getenv("SUMMARY_MAX_CHARS", "12000")))
SUMMARY_MAX_OUTPUT_TOKENS = max(256, int(os.getenv("SUMMARY_MAX_OUTPUT_TOKENS", "900")))
MODEL_VOLUME_NAME = os.getenv("WHISPER_MODEL_VOLUME", "yt-downloader-whisper-models")
MAX_DURATION_SECONDS = int(os.getenv("TRANSCRIPTION_MAX_DURATION_SECONDS", "14400"))
MAX_AUDIO_BYTES = int(os.getenv("TRANSCRIPTION_MAX_AUDIO_MB", "2048")) * 1024 * 1024
GPU_TYPE = os.getenv("WHISPER_GPU", "T4") or "T4"
MIN_CONTAINERS = max(0, int(os.getenv("MODAL_MIN_CONTAINERS", "0")))
MAX_CONTAINERS = max(MIN_CONTAINERS, int(os.getenv("MODAL_MAX_CONTAINERS", "1")))
SCALEDOWN_WINDOW_SECONDS = min(1200, max(60, int(os.getenv("MODAL_SCALEDOWN_WINDOW_SECONDS", "300"))))

_MODEL = None
_SUMMARY_TOKENIZER = None
_SUMMARY_MODEL = None

app = modal.App(APP_NAME)
model_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)
image = (
    # faster-whisper requires CUDA 12 + cuDNN 9 at runtime. Using the official
    # NVIDIA image provides these as system libraries and avoids fragile
    # namespace-package path discovery for pip-installed CUDA wheels.
    modal.Image.from_registry(
        "nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04",
        add_python="3.11",
    )
    .entrypoint([])
    .apt_install("ffmpeg")
    .pip_install("faster-whisper", "torch", "transformers")
)


@app.function(
    image=image,
    gpu=GPU_TYPE,
    timeout=1800,
    min_containers=MIN_CONTAINERS,
    max_containers=MAX_CONTAINERS,
    scaledown_window=SCALEDOWN_WINDOW_SECONDS,
    volumes={"/root/.cache/huggingface": model_volume},
)
def _summarize_text(text: str, language: str) -> str:
    global _SUMMARY_MODEL, _SUMMARY_TOKENIZER
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if _SUMMARY_MODEL is None:
        _SUMMARY_TOKENIZER = AutoTokenizer.from_pretrained(SUMMARY_MODEL_NAME)
        _SUMMARY_MODEL = AutoModelForCausalLM.from_pretrained(
            SUMMARY_MODEL_NAME, torch_dtype=torch.float16, device_map="auto"
        )
        LOG.info("event=summary_model_loaded model=%s", SUMMARY_MODEL_NAME)
    messages = [
        {"role": "system", "content": "You produce accurate, concise summaries of spoken transcripts."},
        {"role": "user", "content": (
            "Summarize only the transcript below. Do not invent facts. "
            f"Write in {language}. Include an overview and key points; include action items only if explicitly present.\n\n"
            f"TRANSCRIPT:\n{text}"
        )},
    ]
    inputs = _SUMMARY_TOKENIZER.apply_chat_template(messages, return_tensors="pt", add_generation_prompt=True)
    inputs = inputs.to(_SUMMARY_MODEL.device)
    with torch.inference_mode():
        output = _SUMMARY_MODEL.generate(inputs, max_new_tokens=SUMMARY_MAX_OUTPUT_TOKENS, do_sample=False)
    return _SUMMARY_TOKENIZER.decode(output[0][inputs.shape[-1]:], skip_special_tokens=True).strip()


def _summarize_transcript(text: str, language: str) -> str:
    chunks = [text[index:index + SUMMARY_MAX_CHARS] for index in range(0, len(text), SUMMARY_MAX_CHARS)]
    summaries = [_summarize_text(chunk, language) for chunk in chunks]
    return summaries[0] if len(summaries) == 1 else _summarize_text("\n\n".join(summaries), language)


def transcribe(
    source_url: str, title: str = "Transcript", source_kind: str = "r2",
    duration: float | None = None, summarize: bool = False, summary_language: str = "en",
) -> dict[str, object]:
    """Download temporary audio and return timestamped speech-to-text."""
    from urllib.request import Request, urlopen
    # The official CUDA runtime image supplies cuBLAS/cuDNN system libraries.
    global _MODEL
    job_started = time.perf_counter()
    logging.basicConfig(
        level=_log_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )
    LOG.info("event=transcription_job_started source_kind=%s model=%s gpu=%s", source_kind, MODEL_NAME, GPU_TYPE)

    with tempfile.TemporaryDirectory(prefix="transcription-") as tmp:
        directory = Path(tmp)
        if duration and float(duration) > MAX_DURATION_SECONDS:
            raise ValueError("This media is longer than the transcription limit")
        audio = directory / "source.mp3"
        if source_kind == "r2":
            request = Request(source_url, headers={"User-Agent": "yt-downloader-transcriber/1.0"})
            with urlopen(request, timeout=60) as response, audio.open("wb") as output:
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length > MAX_AUDIO_BYTES:
                    raise ValueError("The source audio is larger than the transcription limit")
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise ValueError("The source audio is larger than the transcription limit")
                    output.write(chunk)
            LOG.info("event=audio_download_finished duration_seconds=%.2f size_bytes=%s", time.perf_counter() - job_started, audio.stat().st_size)
        else:
            raise ValueError("Only temporary uploaded audio is accepted")
        if audio.stat().st_size > MAX_AUDIO_BYTES:
            raise ValueError("The source audio is larger than the transcription limit")

        if _MODEL is None:
            from faster_whisper import WhisperModel

            model_started = time.perf_counter()
            _MODEL = WhisperModel(MODEL_NAME, device="cuda", compute_type="float16")
            LOG.info("event=model_load_finished duration_seconds=%.2f model=%s", time.perf_counter() - model_started, MODEL_NAME)
        else:
            LOG.info("event=model_reused model=%s", MODEL_NAME)
        model = _MODEL
        inference_started = time.perf_counter()
        segments, detected = model.transcribe(
            str(audio),
            vad_filter=True,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            word_timestamps=False,
        )
        collected = []
        text_parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                text_parts.append(text)
                collected.append({"start": float(segment.start), "text": text})
        summary = _summarize_transcript(" ".join(text_parts), summary_language) if summarize else ""
        LOG.info(
            "event=inference_finished duration_seconds=%.2f total_duration_seconds=%.2f segments=%s summarize=%s",
            time.perf_counter() - inference_started,
            time.perf_counter() - job_started,
            len(collected),
            summarize,
        )
        LOG.info("event=transcription_job_finished total_duration_seconds=%.2f", time.perf_counter() - job_started)
        return {
            "title": str(title or "Transcript"),
            "language": str(getattr(detected, "language", None) or "unknown"),
            "duration": None,
            "text": " ".join(text_parts),
            "segments": collected,
            "summary": summary,
        }
