"""PII redaction tests for run-request.py (0.6.0).

The patterns one by one (hits, exemptions, and the numbers in code they must
leave alone), then end-to-end runs in both modes against the local server.
Every value here is a reserved or published test value: 555-01xx phone
numbers, the 4111/3782 test cards, the documentation SSN.
"""
import json
import os
import unittest
from unittest import mock

from test_run_request import mod, run_main_io, _RunnerFixture, _Handler
from test_build_mode import _BuildFixture


def redact(text):
    counts = {}
    return mod.redact_pii(text, (counts, {})), counts


class PatternTests(unittest.TestCase):
    def assertRedacted(self, text, kind, placeholder):
        out, counts = redact(text)
        self.assertEqual(counts, {kind: 1}, text)
        self.assertIn(placeholder, out)

    def assertUntouched(self, text):
        out, counts = redact(text)
        self.assertEqual((out, counts), (text, {}), text)

    def test_email(self):
        self.assertRedacted("mail jane.roe@university.edu today", "email",
                            "[REDACTED-EMAIL-1]")
        self.assertRedacted('email = "j.roe+lists@mail.co.uk"', "email",
                            "[REDACTED-EMAIL-1]")

    def test_email_exemptions(self):
        for text in ("user@example.com", "a@b.example.org", "x@host.test",
                     "x@foo.invalid", "root@localhost.localhost",
                     "git@github.com:org/repo.git",
                     "noreply@anthropic.com", "no-reply@service.io",
                     "icon@2x.png", "logo@3x.webp", "@property", "react@18.3.1",
                     "npm i pkg@latest"):
            self.assertUntouched(text)

    def test_phone(self):
        for text in ("call (315) 555-0142", "315-555-0142", "315.555.0142",
                     "+1 315 555 0142", "+44 20 7946 0958",
                     "+44 (0)20 7946 0958", "+49 30 901820",
                     "+1(315) 555-0142", "+82-55-540-6441",
                     "+13155550142", "1-315-555-0142", "1.315.555.0142"):
            self.assertRedacted(text, "phone", "[REDACTED-PHONE-1]")

    def test_phone_extension_stays_outside(self):
        out, counts = redact("call 315-555-0142x89")
        self.assertEqual((out, counts),
                         ("call [REDACTED-PHONE-1]x89", {"phone": 1}))

    def test_phone_digit_bounds(self):
        for text in ("+44 20", "+1 2345 6789 0123 4567",  # 4 and 17 digits
                     "+1792741541", "+1792741541000"):  # timestamps
            self.assertUntouched(text)

    def test_placeholders_pass_through(self):
        self.assertUntouched("[REDACTED-EMAIL-1] and [REDACTED-PHONE-2]")

    def test_numbering_continues_past_existing_placeholders(self):
        out, obj_counts = mod.redact_request(
            {"messages": [{"content": "round one: [REDACTED-EMAIL-1]; "
                                      "new: bob@uni.edu"}]})
        self.assertEqual(out["messages"][0]["content"],
                         "round one: [REDACTED-EMAIL-1]; "
                         "new: [REDACTED-EMAIL-2]")
        self.assertEqual(obj_counts, {"email": 1})

    def test_ssn(self):
        self.assertRedacted("SSN 123-45-6789.", "ssn", "[REDACTED-SSN-1]")

    def test_ssn_invalid_areas_untouched(self):
        for text in ("000-12-3456", "666-12-3456", "912-34-5678",
                     "123-00-4567", "123-45-0000"):
            self.assertUntouched(text)

    def test_card(self):
        for text in ("4111 1111 1111 1111", "4111-1111-1111-1111",
                     "4111111111111111", "3782 822463 10005",
                     "378282246310005", "6011 1111 1111 1117",
                     "2221 0000 0000 0009"):
            self.assertRedacted(text, "card", "[REDACTED-CARD-1]")

    def test_card_needs_luhn_and_prefix(self):
        for text in ("4111 1111 1111 1112",   # fails Luhn
                     "1111 1111 1111 1117",   # Luhn-valid, no card prefix
                     "411111111111111",       # 15 digits but not Amex
                     "4111-1111 1111 1111",   # mixed separators
                     "2800 0000 0000 0006"):  # Luhn-valid, past 2720
            self.assertUntouched(text)

    def test_numbers_in_code_untouched(self):
        for text in ("created 1792741541", "ts_ms = 1792741541000",
                     "ts_us = 1792741541000000", "2026-10-23",
                     "DOI 10.1177/2515245918817284",
                     "DOI 10.1093/mind/110.440.1027", "x = 0.4111111111111111",
                     "version 1.2.3", "host 192.168.100.200",
                     "Vols. 270-273 2339", "a + 1 2 3",
                     "+1 192.168.100.200", "at +1 2026-10-23 12:00",
                     "hex 4242424242424242abc"):
            self.assertUntouched(text)

    def test_two_x_domain_is_a_real_address(self):
        self.assertRedacted("staff@2x.edu", "email", "[REDACTED-EMAIL-1]")

    def test_same_value_same_number_counts_every_replacement(self):
        out, counts = redact("a@uni.edu, b@uni.edu, A@uni.edu, "
                             "315-555-0142, (315) 555-0142")
        self.assertEqual(counts, {"email": 3, "phone": 2})
        self.assertEqual(out, "[REDACTED-EMAIL-1], [REDACTED-EMAIL-2], "
                              "[REDACTED-EMAIL-1], [REDACTED-PHONE-1], "
                              "[REDACTED-PHONE-1]")

    def test_redact_obj_walks_keys_and_values(self):
        counts = {}
        obj = {"model": "m", "jane@uni.edu": 1,
               "messages": [{"content": "from jane@uni.edu"}, 7, None]}
        out = mod.redact_obj(obj, (counts, {}))
        self.assertEqual(out["messages"][0]["content"],
                         "from [REDACTED-EMAIL-1]")
        self.assertIn("[REDACTED-EMAIL-1]", out)
        self.assertNotIn("jane@uni.edu", out)
        self.assertEqual(out["messages"][1:], [7, None])
        self.assertEqual(counts, {"email": 2})

    def test_colliding_keys_raise(self):
        with self.assertRaises(ValueError):
            mod.redact_obj({"a@uni.edu": 1, "[REDACTED-EMAIL-1]": 2}, ({}, {}))


PII_PROMPT = ("Review this.\nauthor = jane.roe@university.edu\n"
              "phone = (315) 555-0142\nssn = 123-45-6789\n"
              "card = 4111 1111 1111 1111\n")
ORIGINALS = ("jane.roe", "555-0142", "123-45-6789", "4111 1111")
ALL_FOUR = {"email": 1, "phone": 1, "ssn": 1, "card": 1}


class BuildModeRedactionTests(_BuildFixture, unittest.TestCase):
    def run_build(self, text):
        url = self.json_server("the review")
        prompt = self.write_prompt(text)
        with self.patch_provider("openai", url):
            out, _err, code = run_main_io(
                ["--long", "--no-stream", "--prompt-file", prompt, "openai",
                 self.base], {"OPENAI_API_KEY": "k"})
        return json.loads(out), code

    def test_sent_body_and_artifacts_carry_placeholders_only(self):
        envelope, code = self.run_build(PII_PROMPT)
        self.assertEqual(code, 0)
        self.assertEqual(envelope["redactions"], ALL_FOUR)
        sent = json.dumps(self.sent())
        for placeholder in ("[REDACTED-EMAIL-1]", "[REDACTED-PHONE-1]",
                            "[REDACTED-SSN-1]", "[REDACTED-CARD-1]"):
            self.assertIn(placeholder, sent)
        for path in (self.base + "-request.json", self.base + "-log.txt",
                     self.base + "-envelope.json"):
            with open(path) as f:
                content = f.read()
            for original in ORIGINALS:
                self.assertNotIn(original, content, path)
        for original in ORIGINALS:
            self.assertNotIn(original, sent)
        with open(self.base + "-log.txt") as f:
            self.assertIn("redacted before sending: card=1, email=1, "
                          "phone=1, ssn=1", f.read())

    def test_model_field_is_scanned_too(self):
        url = self.json_server()
        prompt = self.write_prompt("clean")
        with self.patch_provider("openai", url):
            out, _err, code = run_main_io(
                ["--long", "--no-stream", "--prompt-file", prompt,
                 "--model", "jane@uni.edu", "openai", self.base],
                {"OPENAI_API_KEY": "k"})
        self.assertEqual(self.sent()["model"], "[REDACTED-EMAIL-1]")

    def test_gate_refusal_still_reports_redactions(self):
        prompt = self.write_prompt(PII_PROMPT)
        out, _err, code = run_main_io(
            ["--prompt-file", prompt, "openai", self.base],
            {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 2)
        envelope = json.loads(out)
        self.assertIn("long-path request refused", envelope["detail"])
        self.assertEqual(envelope["redactions"], ALL_FOUR)

    def test_clean_prompt_has_no_redactions_field(self):
        envelope, code = self.run_build("nothing personal here")
        self.assertEqual(code, 0)
        self.assertNotIn("redactions", envelope)

    def test_redaction_failure_fails_closed(self):
        url = self.json_server()
        prompt = self.write_prompt(PII_PROMPT)
        with self.patch_provider("openai", url), \
                mock.patch.object(mod, "redact_pii",
                                  side_effect=RuntimeError("jane@uni.edu")):
            out, _err, code = run_main_io(
                ["--long", "--prompt-file", prompt, "openai", self.base],
                {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 2)
        envelope = json.loads(out)
        self.assertEqual(envelope["status"], "usage_error")
        self.assertIn("nothing was sent (RuntimeError)", envelope["detail"])
        self.assertNotIn("jane", out)
        self.assertEqual(_Handler.requests, [])


class LegacyModeRedactionTests(_RunnerFixture, unittest.TestCase):
    def test_legacy_body_redacted_and_input_file_untouched(self):
        url = self.start_server(lambda h: h.send_json(200, {
            "choices": [{"message": {"content": "ok"},
                         "finish_reason": "stop"}]}))
        req = self.write_request({"model": "m", "reasoning_effort": "low",
                                  "messages": [{"role": "user",
                                                "content": PII_PROMPT}]})
        with open(req) as f:
            before = f.read()
        with self.patch_provider("openai", url):
            out, _err, code = run_main_io(["--no-stream", "openai", req,
                                           self.base],
                                          {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["redactions"], ALL_FOUR)
        sent = json.dumps(_Handler.requests[0][1])
        for original in ORIGINALS:
            self.assertNotIn(original, sent)
        with open(req) as f:
            self.assertEqual(f.read(), before)

    def test_duplicate_key_cannot_smuggle_a_value(self):
        # json.loads keeps the last "messages"; the raw bytes still hold the
        # first. Only the re-serialized scanned object may reach the wire.
        url = self.start_server(lambda h: h.send_json(200, {
            "choices": [{"message": {"content": "ok"},
                         "finish_reason": "stop"}]}))
        req = os.path.join(self.dir.name, "dup.json")
        with open(req, "w") as f:
            f.write('{"model": "m", "reasoning_effort": "low", '
                    '"messages": [{"role": "user", "content": "jane@uni.edu"}], '
                    '"messages": [{"role": "user", "content": "hello"}]}')
        with self.patch_provider("openai", url):
            out, _err, code = run_main_io(["--no-stream", "openai", req,
                                           self.base],
                                          {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(_Handler.raw_bodies[0].count(b"jane"), 0)

    def test_legacy_redaction_failure_fails_closed(self):
        url = self.start_server(lambda h: h.send_json(200, {}))
        req = self.write_request({"model": "m", "reasoning_effort": "low",
                                  "messages": [{"role": "user",
                                                "content": "x"}]})
        with self.patch_provider("openai", url), \
                mock.patch.object(mod, "redact_pii",
                                  side_effect=RuntimeError("boom")):
            out, _err, code = run_main_io(["openai", req, self.base],
                                          {"OPENAI_API_KEY": "k"})
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "usage_error")
        self.assertEqual(_Handler.requests, [])


if __name__ == "__main__":
    unittest.main()
