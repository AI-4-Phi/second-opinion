"""Build-mode tests for run-request.py (0.2.0).

Strict parser, model/effort resolution, prompt-file checks, request building,
the gate on built bytes, the -request.json artifact, and end-to-end build
runs. Reuses the harness (module object, local HTTP server, env scrubbing)
from test_run_request — same stdlib-only rules.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from test_run_request import (mod, run_main, run_main_io, RUNNER_ENV,
                              _Handler, _RunnerFixture, openai_completion)


def call_helper(fn, *args):
    """Call a runner helper that may usage_error() (which raises SystemExit).

    Returns (result, envelope, exit_code): on success (result, None, None);
    on usage_error (None, parsed_envelope, 2).
    """
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            return fn(*args), None, None
    except SystemExit as e:
        return None, json.loads(out.getvalue()), e.code


class HelperGuard(unittest.TestCase):
    """Direct helper calls: no inherited envelope path, no host-env leakage.

    run_main_io scrubs RUNNER_ENV, but direct helper calls bypass it — and
    resolve_model reads os.environ, so a host-exported
    SECOND_OPINION_*_MODEL (the documented user override) would turn the
    default-fallthrough assertions red. Scrub here, restore via patch.dict.
    """

    def setUp(self):
        self.addCleanup(setattr, mod, "ENVELOPE_PATH", None)
        mod.ENVELOPE_PATH = None
        env_guard = mock.patch.dict(os.environ)
        env_guard.start()
        self.addCleanup(env_guard.stop)
        for var in RUNNER_ENV:
            os.environ.pop(var, None)


class ParseArgsTests(HelperGuard):
    def parse(self, argv):
        return call_helper(mod.parse_args, argv)

    def test_legacy_shape_parses(self):
        (opts, pos), env, code = self.parse(
            ["--long", "kimi", "req.json", "base"])
        self.assertIsNone(env)
        self.assertEqual(opts, {"--long": True})
        self.assertEqual(pos, ["kimi", "req.json", "base"])

    def test_build_shape_parses(self):
        (opts, pos), env, code = self.parse(
            ["--prompt-file", "p.txt", "--model", "m", "--effort", "low",
             "--no-stream", "kimi", "base"])
        self.assertIsNone(env)
        self.assertEqual(opts, {"--prompt-file": "p.txt", "--model": "m",
                                "--effort": "low", "--no-stream": True})
        self.assertEqual(pos, ["kimi", "base"])

    def test_flags_allowed_after_positionals(self):
        (opts, pos), env, _ = self.parse(["kimi", "base", "--prompt-file", "p"])
        self.assertIsNone(env)
        self.assertEqual(opts["--prompt-file"], "p")

    def assert_shape_error(self, argv, contains):
        result, envelope, code = self.parse(argv)
        self.assertIsNone(result)
        self.assertEqual(code, 2)
        self.assertEqual(envelope["status"], "usage_error")
        self.assertIn(contains, envelope["detail"])

    def test_trailing_valueless_flag(self):
        self.assert_shape_error(["kimi", "base", "--prompt-file"],
                                "requires a value")

    def test_empty_value(self):
        self.assert_shape_error(["--prompt-file", "", "kimi", "base"],
                                "requires a value")

    def test_flag_like_value(self):
        self.assert_shape_error(["--prompt-file", "--long", "kimi", "base"],
                                "requires a value")

    def test_repeated_value_flag(self):
        self.assert_shape_error(
            ["--prompt-file", "a", "--prompt-file", "b", "kimi", "base"],
            "more than once")

    def test_unknown_flag(self):
        self.assert_shape_error(["--frobnicate", "kimi", "r", "base"],
                                "unknown flag")


class ResolveModelTests(HelperGuard):
    def test_flag_beats_env_beats_default(self):
        with mock.patch.dict(os.environ,
                             {"SECOND_OPINION_KIMI_MODEL": "env-model"}):
            self.assertEqual(mod.resolve_model("kimi", "flag-model"),
                             "flag-model")
            self.assertEqual(mod.resolve_model("kimi", None), "env-model")
        self.assertEqual(mod.resolve_model("kimi", None), "kimi-k3")

    def test_whitespace_env_override_falls_through(self):
        with mock.patch.dict(os.environ, {"SECOND_OPINION_KIMI_MODEL": "  "}):
            self.assertEqual(mod.resolve_model("kimi", None), "kimi-k3")

    def test_env_var_name_is_uppercased_provider(self):
        with mock.patch.dict(os.environ,
                             {"SECOND_OPINION_DEEPSEEK_MODEL": "ds-x"}):
            self.assertEqual(mod.resolve_model("deepseek", None), "ds-x")

    def test_defaults_cover_every_provider(self):
        self.assertEqual(set(mod.DEFAULT_MODELS), set(mod.PROVIDERS))
        self.assertEqual(mod.DEFAULT_MODELS["gemini"], "gemini-3.1-pro-preview")


class ResolveEffortTests(HelperGuard):
    def test_explicit_effort_lowercased(self):
        self.assertEqual(mod.resolve_effort("kimi", "kimi-k3", "LOW"), "low")
        self.assertEqual(mod.resolve_effort("openai", "gpt-5.6-sol", "max"),
                         "max")

    def test_invalid_effort_names_valid_set(self):
        _, envelope, code = call_helper(mod.resolve_effort,
                                        "kimi", "kimi-k3", "banana")
        self.assertEqual(code, 2)
        self.assertIn("low|medium|high|xhigh|max", envelope["detail"])

    def test_gemini_refuses_effort(self):
        _, envelope, code = call_helper(mod.resolve_effort,
                                        "gemini", "gemini-3.1-pro-preview",
                                        "low")
        self.assertEqual(code, 2)
        self.assertIn("reasoning_effort", envelope["detail"])

    def test_kimi_k3_absent_effort_injects_low(self):
        self.assertEqual(mod.resolve_effort("kimi", "kimi-k3", None), "low")

    def test_injection_is_model_keyed_not_provider_keyed(self):
        # An override to a model the runner does not know must NOT be injected.
        self.assertIsNone(mod.resolve_effort("kimi", "kimi-k4-new", None))
        self.assertIsNone(mod.resolve_effort("openai", "gpt-5.6-sol", None))


class ReadPromptFileTests(HelperGuard):
    def setUp(self):
        HelperGuard.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_valid_utf8_returned(self):
        p = self.path("p.txt")
        with open(p, "w") as f:
            f.write("review this — thoroughly")
        result, _, _ = call_helper(mod.read_prompt_file, p)
        self.assertEqual(result, "review this — thoroughly")

    def test_missing_file(self):
        _, envelope, code = call_helper(mod.read_prompt_file,
                                        self.path("nope.txt"))
        self.assertEqual(code, 2)
        self.assertIn("missing or empty", envelope["detail"])

    def test_empty_file(self):
        p = self.path("empty.txt")
        open(p, "w").close()
        _, envelope, code = call_helper(mod.read_prompt_file, p)
        self.assertEqual(code, 2)
        self.assertIn("missing or empty", envelope["detail"])

    def test_invalid_utf8(self):
        p = self.path("bad.txt")
        with open(p, "wb") as f:
            f.write(b"\xff\xfe\x00garbage")
        _, envelope, code = call_helper(mod.read_prompt_file, p)
        self.assertEqual(code, 2)
        self.assertIn("not valid UTF-8", envelope["detail"])


class BuildRequestTests(HelperGuard):
    def test_openai_compatible_shape_matches_jq_template(self):
        obj = mod.build_request("kimi", "kimi-k3", "low", "the prompt")
        self.assertEqual(obj, {
            "model": "kimi-k3",
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": mod.SYSTEM_PROMPT},
                {"role": "user", "content": "the prompt"}]})

    def test_effort_omitted_when_none(self):
        obj = mod.build_request("openai", "gpt-5.6-sol", None, "p")
        self.assertNotIn("reasoning_effort", obj)

    def test_gemini_shape_carries_no_model(self):
        obj = mod.build_request("gemini", "gemini-3.1-pro-preview", None, "p")
        self.assertEqual(obj, {
            "systemInstruction": {"parts": [{"text": mod.SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": "p"}]}]})

    def test_system_prompt_is_the_documented_string(self):
        self.assertEqual(mod.SYSTEM_PROMPT,
                         "You are an expert reviewer providing a second "
                         "opinion. Be specific, cite evidence, and explain "
                         "your reasoning.")


if __name__ == "__main__":
    unittest.main()
