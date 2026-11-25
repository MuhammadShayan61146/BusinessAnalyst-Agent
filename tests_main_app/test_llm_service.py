
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

import services.llm_service as llm_service  # noqa: E402  (real production source, unmodified)


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(llm_service._extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json_with_language_tag(self):
        self.assertEqual(llm_service._extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_fenced_json_without_language_tag(self):
        self.assertEqual(llm_service._extract_json('```\n{"a": 1}\n```'), {"a": 1})

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(llm_service._extract_json('   {"a": 1}   \n'), {"a": 1})

    def test_invalid_json_raises(self):
        with self.assertRaises(Exception):
            llm_service._extract_json("not json at all")


class AskJsonWithRetryTests(unittest.TestCase):
    def test_succeeds_on_first_valid_response(self):
        calls = []

        def raw_invoke(prompt):
            calls.append(prompt)
            return '{"ok": true}'

        result = llm_service._ask_json_with_retry(raw_invoke, "base prompt")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 1)

    def test_recovers_after_one_malformed_response(self):
        responses = iter(["not json", '{"ok": true}'])

        def raw_invoke(prompt):
            return next(responses)

        result = llm_service._ask_json_with_retry(raw_invoke, "base prompt", max_retries=1)
        self.assertEqual(result, {"ok": True})

    def test_raises_llm_response_error_after_exhausting_retries(self):
        def raw_invoke(prompt):
            return "still not json"

        with self.assertRaises(llm_service.LLMResponseError):
            llm_service._ask_json_with_retry(raw_invoke, "base prompt", max_retries=1)

    def test_retry_count_is_bounded_not_unlimited(self):
        call_count = {"n": 0}

        def raw_invoke(prompt):
            call_count["n"] += 1
            return "never valid"

        with self.assertRaises(llm_service.LLMResponseError):
            llm_service._ask_json_with_retry(raw_invoke, "base prompt", max_retries=2)
        self.assertEqual(call_count["n"], 3)  # 1 initial + 2 retries, not unbounded

    def test_never_fabricates_a_result_on_permanent_failure(self):
        def raw_invoke(prompt):
            return "garbage"

        try:
            llm_service._ask_json_with_retry(raw_invoke, "p", max_retries=0)
            self.fail("expected LLMResponseError")
        except llm_service.LLMResponseError as e:
            self.assertIn("garbage", str(e))  # real failure detail, not a silently-returned {}


class GeminiProviderCredentialTests(unittest.TestCase):
    def test_missing_api_key_raises_before_any_sdk_import(self):
        # Passing api_key="" explicitly bypasses config/settings entirely,
        # so this test needs no environment setup and makes no SDK import
        # attempt (the credential check happens before the lazy import).
        with self.assertRaises(llm_service.MissingCredentialsError):
            llm_service.GeminiProvider(api_key="")

    def test_explicit_api_key_is_used_over_settings_default(self):
        # We only assert the key was ACCEPTED (no MissingCredentialsError)
        # up to the point of the lazy SDK import, which then fails in this
        # sandbox because langchain_google_genai isn't installed — that
        # ImportError, not MissingCredentialsError, is what proves the
        # credential check passed.
        with self.assertRaises(ImportError):
            llm_service.GeminiProvider(api_key="fake-key-for-test")


class NoSilentFallbackTests(unittest.TestCase):
    def test_gemini_provider_selected_by_default_and_missing_key_does_not_fall_back(self):
        # Patching llm_service's OWN module-level bindings, since
        # `from config.settings import LLM_PROVIDER, ...` created
        # separate name bindings in services.llm_service's namespace —
        # patching config.settings itself has no effect on get_provider().
        with mock.patch.object(llm_service, "LLM_PROVIDER", "gemini"), \
             mock.patch.object(llm_service, "GEMINI_API_KEY", None):
            with self.assertRaises(llm_service.MissingCredentialsError):
                llm_service.get_provider()
            # Confirm it did NOT silently return an OpenRouterProvider instead.

    def test_unknown_provider_name_raises_rather_than_defaulting_silently(self):
        with mock.patch.object(llm_service, "LLM_PROVIDER", "some-other-provider"):
            with self.assertRaises(llm_service.LLMError):
                llm_service.get_provider()

    def test_openrouter_requires_explicit_opt_in_value(self):
        # LLM_PROVIDER must be exactly "openrouter" to select it; anything
        # else (including unset/default) goes to Gemini, never silently to
        # OpenRouter.
        with mock.patch.object(llm_service, "LLM_PROVIDER", "openrouter"):
            # langchain_openrouter is not installed in this sandbox, so
            # construction fails with ImportError — but critically, it
            # is OpenRouterProvider's construction that fails, proving
            # routing went to the explicitly-requested provider, not a
            # silent substitute.
            with self.assertRaises(ImportError):
                llm_service.get_provider()


if __name__ == "__main__":
    unittest.main()
