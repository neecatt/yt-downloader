"""Standalone Celery application entry point for the transcription service."""

from ..queue.config import app
from .transcription import process_transcription  # noqa: F401

__all__ = ["app", "process_transcription"]
