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


class _BuildFixture(_RunnerFixture):
    """Adds prompt-file and server conveniences for build-mode runs."""

    def write_prompt(self, text="review this please"):
        path = os.path.join(self.dir.name, "prompt.txt")
        with open(path, "w") as f:
            f.write(text)
        return path

    def json_server(self, text="the review"):
        return self.start_server(
            lambda h: h.send_json(200, openai_completion(text,
                                                         {"total_tokens": 3})))

    def sse_server(self, text="the review"):
        return self.start_server(lambda h: h.send_sse([
            {"choices": [{"delta": {"content": text}}],
             "usage": {"total_tokens": 5}},
            "[DONE]"]))

    def sent(self, index=0):
        return _Handler.requests[index][1]


class ModeShapeTests(_BuildFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.prompt = self.write_prompt()

    def assert_usage(self, argv, env=None, contains=""):
        envelope, code = run_main(argv, env)
        self.assertEqual(code, 2)
        self.assertEqual(envelope["status"], "usage_error")
        self.assertIn(contains, envelope["detail"])
        return envelope

    def test_build_three_positionals_rejected(self):
        self.assert_usage(
            ["--prompt-file", self.prompt, "kimi", self.base, "extra"],
            contains="exactly two")

    def test_build_one_positional_rejected(self):
        self.assert_usage(["--prompt-file", self.prompt, "kimi"],
                          contains="exactly two")

    def test_model_flag_requires_prompt_file(self):
        req = self.write_request({"model": "kimi-k3",
                                  "reasoning_effort": "low"})
        self.assert_usage(["--model", "x", "kimi", req, self.base],
                          contains="--prompt-file")

    def test_effort_flag_requires_prompt_file(self):
        req = self.write_request({"model": "kimi-k3",
                                  "reasoning_effort": "low"})
        self.assert_usage(["--effort", "low", "kimi", req, self.base],
                          contains="--prompt-file")

    def test_build_reaches_key_check(self):
        # Proof the two-positional build shape parses and resolves: the
        # failure is the missing key, named with resolved provider AND model.
        envelope = self.assert_usage(
            ["--prompt-file", self.prompt, "kimi", self.base],
            contains="MOONSHOT_API_KEY not set")
        self.assertIn("kimi-k3", envelope["detail"])

    def test_malformed_shape_preserves_preseeded_envelope(self):
        seeded = json.dumps({"status": "completed", "chars": 1}) + "\n"
        envelope_path = self.base + "-envelope.json"
        for argv in (
                ["--prompt-file", self.prompt, "kimi", self.base, "extra"],
                ["--model", "x", "kimi", "req.json", self.base],
                ["--prompt-file"],):
            with open(envelope_path, "w") as f:
                f.write(seeded)
            _envelope, code = run_main(argv)
            self.assertEqual(code, 2)
            with open(envelope_path) as f:
                self.assertEqual(f.read(), seeded,
                                 "shape error must not touch %r" % argv)

    def test_valid_shape_usage_error_claims_envelope(self):
        envelope_path = self.base + "-envelope.json"
        with open(envelope_path, "w") as f:
            f.write(json.dumps({"status": "completed", "chars": 1}) + "\n")
        _envelope, code = run_main(
            ["--prompt-file", self.prompt, "frontier", self.base])
        self.assertEqual(code, 2)
        with open(envelope_path) as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk["status"], "usage_error")
        self.assertIn("unknown provider", on_disk["detail"])


class BuildResolutionThroughMainTests(_BuildFixture, unittest.TestCase):
    """Model/effort resolution observed in the request a live server receives."""

    def run_build(self, extra_argv=(), env_extra=None, provider="kimi",
                  key=("MOONSHOT_API_KEY", "k"), server="sse"):
        url = self.sse_server() if server == "sse" else self.json_server()
        prompt = self.write_prompt()
        env = {key[0]: key[1]}
        env.update(env_extra or {})
        with self.patch_provider(provider, url):
            envelope, code = run_main(
                list(extra_argv) + ["--prompt-file", prompt, provider,
                                    self.base], env)
        return envelope, code

    def test_flag_beats_env_beats_default(self):
        envelope, code = self.run_build(
            ["--model", "flag-model"],
            {"SECOND_OPINION_KIMI_MODEL": "env-model"})
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["model"], "flag-model")

    def test_env_override_beats_default(self):
        envelope, code = self.run_build(
            env_extra={"SECOND_OPINION_KIMI_MODEL": "env-model"})
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["model"], "env-model")
        # model-keyed injection: an override away from kimi-k3 gets NO effort
        self.assertNotIn("reasoning_effort", self.sent())

    def test_default_model_with_injection(self):
        envelope, code = self.run_build()
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["model"], "kimi-k3")
        self.assertEqual(self.sent()["reasoning_effort"], "low")
        self.assertEqual(envelope["model"], "kimi-k3")

    def test_whitespace_env_override_falls_through(self):
        envelope, code = self.run_build(
            env_extra={"SECOND_OPINION_KIMI_MODEL": "   "})
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["model"], "kimi-k3")

    def test_effort_case_lowered_in_body(self):
        envelope, code = self.run_build(["--effort", "LOW"])
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["reasoning_effort"], "low")

    def test_explicit_high_effort_blocks_without_long(self):
        prompt = self.write_prompt()
        envelope, code = run_main(
            ["--prompt-file", prompt, "--effort", "max", "kimi", self.base],
            {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertIn("long-path request refused", envelope["detail"])
        self.assertIn("kimi-k3", envelope["detail"])

    def test_explicit_high_effort_carried_with_long(self):
        envelope, code = self.run_build(["--effort", "max", "--long"])
        self.assertEqual(code, 0)
        self.assertEqual(self.sent()["reasoning_effort"], "max")

    def test_legacy_mode_ignores_env_override(self):
        # If legacy consulted SECOND_OPINION_KIMI_MODEL, the substituted model
        # would dodge the unset-effort gate. It must still gate-block.
        req = self.write_request({"model": "kimi-k3"})
        envelope, code = run_main(
            ["kimi", req, self.base],
            {"MOONSHOT_API_KEY": "k",
             "SECOND_OPINION_KIMI_MODEL": "other-model"})
        self.assertEqual(code, 2)
        self.assertIn("long-path request refused", envelope["detail"])


class GeminiBuildTests(_BuildFixture, unittest.TestCase):
    def gemini_url(self, url):
        return url + "/v1beta/models/{model}:generateContent"

    def run_gemini(self, extra_argv=(), env_extra=None):
        url = self.start_server(lambda h: h.send_sse([
            {"candidates": [{"content": {"parts": [{"text": "review"}]}}],
             "usageMetadata": {"totalTokenCount": 4}}]))
        prompt = self.write_prompt()
        env = {"GEMINI_API_KEY": "k"}
        env.update(env_extra or {})
        with self.patch_provider("gemini", self.gemini_url(url)):
            envelope, code = run_main(
                list(extra_argv) + ["--prompt-file", prompt, "gemini",
                                    self.base], env)
        return envelope, code

    def test_effort_refused(self):
        prompt = self.write_prompt()
        envelope, code = run_main(
            ["--prompt-file", prompt, "--effort", "low", "gemini", self.base],
            {"GEMINI_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertIn("reasoning_effort", envelope["detail"])

    def test_url_carries_resolved_default_model(self):
        envelope, code = self.run_gemini()
        self.assertEqual(code, 0)
        self.assertIn("gemini-3.1-pro-preview", _Handler.requests[0][0])
        body = self.sent()
        self.assertIn("systemInstruction", body)
        self.assertIn("contents", body)
        self.assertNotIn("model", body)
        self.assertEqual(envelope["model"], "gemini-3.1-pro-preview")

    def test_env_override_resolves_url_model(self):
        envelope, code = self.run_gemini(
            env_extra={"SECOND_OPINION_GEMINI_MODEL": "g-env"})
        self.assertEqual(code, 0)
        self.assertIn("/g-env:", _Handler.requests[0][0])

    def test_model_flag_resolves_url_model(self):
        envelope, code = self.run_gemini(["--model", "g-flag"])
        self.assertEqual(code, 0)
        self.assertIn("/g-flag:", _Handler.requests[0][0])

    def test_missing_key_names_resolved_model(self):
        prompt = self.write_prompt()
        envelope, code = run_main(
            ["--prompt-file", prompt, "gemini", self.base])
        self.assertEqual(code, 2)
        self.assertIn("GEMINI_API_KEY not set", envelope["detail"])
        self.assertIn("gemini-3.1-pro-preview", envelope["detail"])


class BodyShapeTests(_BuildFixture, unittest.TestCase):
    def test_body_is_jq_template_plus_stream_fields(self):
        url = self.sse_server()
        prompt = self.write_prompt("the exact prompt text")
        with self.patch_provider("kimi", url):
            _envelope, code = run_main(
                ["--prompt-file", prompt, "--effort", "low", "kimi",
                 self.base], {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 0)
        body = dict(self.sent())
        self.assertIs(body.pop("stream"), True)
        self.assertEqual(body.pop("stream_options"), {"include_usage": True})
        self.assertEqual(body, {
            "model": "kimi-k3",
            "reasoning_effort": "low",
            "messages": [
                {"role": "system", "content": mod.SYSTEM_PROMPT},
                {"role": "user", "content": "the exact prompt text"}]})


class BuiltGateTests(_BuildFixture, unittest.TestCase):
    def test_built_bytes_cross_gate_refused_without_long(self):
        prompt = self.write_prompt("x" * mod.GATE_BYTES)
        envelope, code = run_main(
            ["--prompt-file", prompt, "openai", self.base],
            {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertIn("long-path request refused", envelope["detail"])
        # build-mode refusals name the resolved provider and model (spec §10)
        self.assertIn("openai", envelope["detail"])
        self.assertIn("gpt-5.6-sol", envelope["detail"])

    def test_built_bytes_cross_gate_runs_with_long(self):
        url = self.sse_server()
        prompt = self.write_prompt("x" * mod.GATE_BYTES)
        with self.patch_provider("openai", url):
            envelope, code = run_main(
                ["--long", "--prompt-file", prompt, "openai", self.base],
                {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(envelope["status"], "completed")

    def test_gemini_size_refusal_names_model(self):
        prompt = self.write_prompt("x" * mod.GATE_BYTES)
        envelope, code = run_main(
            ["--prompt-file", prompt, "gemini", self.base],
            {"GEMINI_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertIn("long-path request refused", envelope["detail"])
        self.assertIn("gemini-3.1-pro-preview", envelope["detail"])


class RequestArtifactTests(_BuildFixture, unittest.TestCase):
    @property
    def artifact(self):
        return self.base + "-request.json"

    def test_absent_after_gate_refusal(self):
        prompt = self.write_prompt("x" * mod.GATE_BYTES)
        _envelope, code = run_main(
            ["--prompt-file", prompt, "openai", self.base],
            {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.artifact))

    def test_absent_after_missing_key(self):
        prompt = self.write_prompt()
        _envelope, code = run_main(
            ["--prompt-file", prompt, "kimi", self.base])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.artifact))

    def test_present_and_pre_injection_after_run(self):
        url = self.sse_server()
        prompt = self.write_prompt()
        with self.patch_provider("kimi", url):
            _envelope, code = run_main(
                ["--prompt-file", prompt, "kimi", self.base],
                {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 0)
        with open(self.artifact) as f:
            artifact = json.load(f)
        self.assertNotIn("stream", artifact)
        self.assertEqual(artifact["model"], "kimi-k3")
        self.assertEqual(artifact["reasoning_effort"], "low")

    def test_artifact_reruns_through_legacy_mode(self):
        url = self.sse_server()
        prompt = self.write_prompt()
        env = {"MOONSHOT_API_KEY": "k"}
        with self.patch_provider("kimi", url):
            _e, code = run_main(
                ["--prompt-file", prompt, "kimi", self.base], env)
            self.assertEqual(code, 0)
            first = self.sent(0)
            _e, code = run_main(["kimi", self.artifact, self.base], env)
            self.assertEqual(code, 0)
        self.assertEqual(first, self.sent(1))

    def test_gemini_artifact_reruns_with_model_arg(self):
        url = self.start_server(lambda h: h.send_sse([
            {"candidates": [{"content": {"parts": [{"text": "r"}]}}]}]))
        tmpl = url + "/v1beta/models/{model}:generateContent"
        prompt = self.write_prompt()
        env = {"GEMINI_API_KEY": "k"}
        with self.patch_provider("gemini", tmpl):
            _e, code = run_main(
                ["--prompt-file", prompt, "gemini", self.base], env)
            self.assertEqual(code, 0)
            _e, code = run_main(
                ["gemini", self.artifact, self.base,
                 "gemini-3.1-pro-preview"], env)
            self.assertEqual(code, 0)
        self.assertEqual(_Handler.requests[0][0], _Handler.requests[1][0])
        self.assertEqual(self.sent(0), self.sent(1))


class MakedirsTests(_BuildFixture, unittest.TestCase):
    def test_build_creates_missing_output_dir(self):
        url = self.sse_server()
        prompt = self.write_prompt()
        base = os.path.join(self.dir.name, "deep", "nested", "out")
        with self.patch_provider("kimi", url):
            envelope, code = run_main(
                ["--prompt-file", prompt, "kimi", base],
                {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(base + "-envelope.json"))

    def test_legacy_creates_missing_output_dir(self):
        url = self.json_server()
        req = self.write_request({"model": "gpt-5.6-terra",
                                  "reasoning_effort": "low"})
        base = os.path.join(self.dir.name, "new", "dir", "out")
        with self.patch_provider("openai", url):
            envelope, code = run_main(
                ["--no-stream", "openai", req, base], {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(base + "-envelope.json"))

    def test_bare_relative_base_still_works(self):
        url = self.json_server()
        req = self.write_request({"model": "gpt-5.6-terra",
                                  "reasoning_effort": "low"})
        cwd = os.getcwd()
        os.chdir(self.dir.name)
        self.addCleanup(os.chdir, cwd)
        with self.patch_provider("openai", url):
            envelope, code = run_main(
                ["--no-stream", "openai", req, "review"],
                {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(
            os.path.join(self.dir.name, "review-envelope.json")))


class BuildEndToEndTests(_BuildFixture, unittest.TestCase):
    def test_streaming_end_to_end(self):
        url = self.sse_server("the full review")
        prompt = self.write_prompt()
        with self.patch_provider("kimi", url):
            out, _err, code = run_main_io(
                ["--prompt-file", prompt, "kimi", self.base],
                {"MOONSHOT_API_KEY": "k"})
        self.assertEqual(code, 0)
        envelope = json.loads(out)
        self.assertEqual(envelope["status"], "completed")
        with open(envelope["text_path"]) as f:
            self.assertEqual(f.read(), "the full review")
        with open(self.base + "-envelope.json") as f:
            self.assertEqual(f.read(), out)  # byte-equal, newline included

    def test_no_stream_end_to_end(self):
        url = self.json_server("the full review")
        prompt = self.write_prompt()
        with self.patch_provider("openai", url):
            out, _err, code = run_main_io(
                ["--no-stream", "--prompt-file", prompt, "openai", self.base],
                {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        envelope = json.loads(out)
        self.assertEqual(envelope["status"], "completed")
        self.assertNotIn("stream", self.sent())
        with open(self.base + "-envelope.json") as f:
            self.assertEqual(f.read(), out)


if __name__ == "__main__":
    unittest.main()
