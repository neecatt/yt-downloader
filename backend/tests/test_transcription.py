import contextlib
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from backend.bot.integrations.transcription import (
        format_transcript,
        transcript_filename,
        transcription_is_configured,
        validate_transcription_url,
    )
except ModuleNotFoundError:
    from bot.integrations.transcription import (
        format_transcript,
        transcript_filename,
        transcription_is_configured,
        validate_transcription_url,
    )


class TranscriptionTests(unittest.TestCase):
    def test_summary_generation_passes_token_fields_to_model(self):
        class FakeImage:
            def __init__(self):
                self.apt_packages = ()
                self.environment = {}

            def entrypoint(self, *_args, **_kwargs):
                return self

            def apt_install(self, *packages, **_kwargs):
                self.apt_packages = packages
                return self

            def env(self, values):
                self.environment.update(values)
                return self

            def pip_install(self, *_args, **_kwargs):
                return self

        class FakeApp:
            def function(self, *_args, **_kwargs):
                return lambda function: function

        fake_modal = types.ModuleType("modal")
        fake_modal.App = lambda _name: FakeApp()
        fake_modal.Volume = SimpleNamespace(from_name=lambda *_args, **_kwargs: object())
        fake_image = FakeImage()
        fake_modal.Image = SimpleNamespace(from_registry=lambda *_args, **_kwargs: fake_image)

        class FakeTensor:
            shape = (1, 3)

            def to(self, device):
                self.device = device
                return self

        class FakeTokenizer:
            def __init__(self):
                self.template_kwargs = None

            def apply_chat_template(self, messages, **kwargs):
                self.messages = messages
                self.template_kwargs = kwargs
                return {"input_ids": FakeTensor(), "attention_mask": FakeTensor()}

            def decode(self, tokens, **_kwargs):
                self.decoded_tokens = tokens
                return "Generated summary"

        class FakeModel:
            def parameters(self):
                return iter([SimpleNamespace(device="cuda")])

            def generate(self, **kwargs):
                self.generation_kwargs = kwargs
                return [[10, 11, 12, 99]]

        fake_torch = types.ModuleType("torch")
        fake_torch.inference_mode = contextlib.nullcontext
        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoModelForCausalLM = object()
        fake_transformers.AutoTokenizer = object()

        module_path = Path(__file__).parents[1] / "modal_transcriber.py"
        spec = importlib.util.spec_from_file_location("modal_transcriber_under_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"modal": fake_modal, "torch": fake_torch, "transformers": fake_transformers}):
            spec.loader.exec_module(module)
            tokenizer = FakeTokenizer()
            model = FakeModel()
            module._SUMMARY_TOKENIZER = tokenizer
            module._SUMMARY_MODEL = model
            summary = module._summarize_text("Transcript text", "English")

        self.assertEqual(summary, "Generated summary")
        self.assertTrue(tokenizer.template_kwargs["return_dict"])
        self.assertIn("input_ids", model.generation_kwargs)
        self.assertIn("attention_mask", model.generation_kwargs)
        self.assertEqual(tokenizer.decoded_tokens, [99])
        self.assertIn("build-essential", fake_image.apt_packages)
        self.assertEqual(fake_image.environment["CC"], "/usr/bin/gcc")
        prompt = tokenizer.messages[1]["content"]
        self.assertIn("Write the summary in English", prompt)
        self.assertIn("Refer to the source as 'the video'", prompt)
        self.assertIn("exactly these Markdown sections", prompt)
        self.assertIn("Do not add any other sections", prompt)
        self.assertNotIn("**Why it matters**", prompt)
        self.assertNotIn("**Next steps**", prompt)
        self.assertIn("If the usable speech is sparse", prompt)

    def test_delivery_caption_uses_detected_speech_language(self):
        from backend.bot.telegram.status import transcription_ready_caption

        caption = transcription_ready_caption("en", "tr")

        self.assertIn("detected language: tr", caption)
        self.assertNotIn("detected language: en", caption)

    def test_queue_requires_private_redis_url(self):
        try:
            from backend.bot.queue import queue_is_configured
        except ModuleNotFoundError:
            from bot.queue import queue_is_configured
        with patch.dict(os.environ, {"TRANSCRIPTION_QUEUE_ENABLED": "true"}, clear=True):
            self.assertFalse(queue_is_configured())

    def test_only_supported_https_hosts_are_accepted(self):
        self.assertEqual(validate_transcription_url("https://youtu.be/example"), "https://youtu.be/example")
        with self.assertRaises(ValueError):
            validate_transcription_url("http://youtu.be/example")
        with self.assertRaises(ValueError):
            validate_transcription_url("https://example.com/audio")
        with self.assertRaises(ValueError):
            validate_transcription_url("https://user:pass@youtu.be/example")

    def test_modal_configuration_requires_both_token_values(self):
        with patch.dict(os.environ, {
            "TRANSCRIPTION_ENABLED": "true",
            "MODAL_TOKEN_ID": "id",
            "MODAL_TOKEN_SECRET": "secret",
        }, clear=True):
            self.assertTrue(transcription_is_configured())
        with patch.dict(os.environ, {"TRANSCRIPTION_ENABLED": "true", "MODAL_TOKEN_ID": "id"}, clear=True):
            self.assertFalse(transcription_is_configured())
        with patch.dict(os.environ, {"TRANSCRIPTION_ENABLED": "false", "MODAL_TOKEN_ID": "id", "MODAL_TOKEN_SECRET": "secret"}, clear=True):
            self.assertFalse(transcription_is_configured())

    def test_format_transcript_includes_timestamps_and_fallback_text(self):
        output = format_transcript({
            "title": "A / Talk",
            "language": "en",
            "segments": [{"start": 65, "text": " Hello   world "}],
            "text": "Hello world",
        })
        self.assertIn("A / Talk", output)
        self.assertIn("[01:05] Hello world", output)

        fallback = format_transcript({"title": "Talk", "language": "en", "segments": [], "text": "Only text"})
        self.assertIn("Only text", fallback)

    def test_filename_is_safe_and_bounded(self):
        filename = transcript_filename("bad/:title?" + "x" * 200)
        self.assertTrue(filename.endswith(".txt"))
        self.assertNotIn("/", filename)
        self.assertLessEqual(len(filename), 125)


if __name__ == "__main__":
    unittest.main()
