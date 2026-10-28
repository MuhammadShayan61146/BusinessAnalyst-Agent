"""
LLM provider abstraction.

Gemini is the default, required provider for this application.
OpenRouter is retained only for explicit opt-in via LLM_PROVIDER=openrouter
(config/settings.py) — there is NO automatic fallback between providers in
either direction anywhere in this module.

Provider-specific SDK calls are isolated to this file; graph nodes
(agent/nodes.py) only ever call the module-level ask_llm_json(prompt)
function below, exactly as before Phase 3C.1 (requirement: preserve the
existing interface so nodes don't need to change).
"""
import json

from config.settings import LLM_PROVIDER, GEMINI_API_KEY, GEMINI_MODEL


class LLMError(Exception):
    """Base class for every error this module raises."""


class MissingCredentialsError(LLMError):
    """Raised when the configured provider has no usable credentials."""


class LLMResponseError(LLMError):
    """
    Raised when the model's response could not be parsed as JSON even
    after the bounded retry. Never silently swallowed into a fabricated
    empty/default result — callers must handle this explicitly.
    """


class LLMProvider:
    """Common interface every concrete provider implements."""

    def ask_json(self, prompt: str) -> dict:
        raise NotImplementedError


def _extract_json(text: str) -> dict:
    """Handles both fenced (```json ... ```) and ordinary JSON text."""
    if not isinstance(text, str):
        raise ValueError(f"Expected string response text, got {type(text).__name__}.")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```")
    return json.loads(cleaned.strip())


def _ask_json_with_retry(raw_invoke, prompt: str, max_retries: int = 1) -> dict:
    """
    Calls raw_invoke(prompt) -> str and parses JSON out of the result.
    On a parse failure, re-prompts with an explicit correction request
    up to `max_retries` additional times before raising
    LLMResponseError. Bounded, documented, never fabricates a result.

    This retry is for MALFORMED JSON specifically. A hard provider-level
    failure (auth, network, rate limit) raised by raw_invoke() propagates
    immediately as LLMError and is NOT retried here — retrying a hard
    failure with the same credentials is unlikely to help and would
    silently multiply billed API calls on, e.g., a bad API key.
    """
    attempt_prompt = prompt + "\nReply with valid JSON only. No extra text."
    last_error = None
    last_text = None
    for _ in range(max_retries + 1):
        text = raw_invoke(attempt_prompt)
        last_text = text
        try:
            return _extract_json(text)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            attempt_prompt = (
                f"{prompt}\nYour previous reply could not be parsed as JSON "
                f"(error: {e}). Reply again with ONLY valid JSON, no markdown "
                f"fences, no extra text."
            )
    truncated = (last_text or "")[:300]
    raise LLMResponseError(
        f"Model response could not be parsed as JSON after {max_retries + 1} "
        f"attempt(s). Last error: {last_error}. Last raw response (truncated): {truncated!r}"
    )


class GeminiProvider(LLMProvider):
    """Wraps langchain_google_genai.ChatGoogleGenerativeAI."""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model or GEMINI_MODEL
        if not self.api_key:
            raise MissingCredentialsError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. Gemini is the "
                "required default provider and this application does not fall "
                "back to another provider automatically. Set the environment "
                "variable, or set LLM_PROVIDER=openrouter explicitly to use "
                "the alternative provider instead."
            )
        
        from langchain_google_genai import ChatGoogleGenerativeAI
        # Ensure model name is clean and compatible with the current SDK version
        clean_model = self.model_name.replace("models/", "")
        self._client = ChatGoogleGenerativeAI(
            model=clean_model, google_api_key=self.api_key, temperature=0
        )

    def _raw_invoke(self, prompt: str) -> str:
        try:
            response = self._client.invoke(prompt)
        except Exception as e:
            raise LLMError(f"Gemini API call failed: {e}") from e
        text = response.content
        if isinstance(text, list):
            text = "".join(p if isinstance(p, str) else p.get("text", "") for p in text)
        return text

    def ask_json(self, prompt: str) -> dict:
        return _ask_json_with_retry(self._raw_invoke, prompt)


class OpenRouterProvider(LLMProvider):
    """
    Retained only for explicit opt-in (LLM_PROVIDER=openrouter). Never
    constructed automatically as a fallback from Gemini.
    """

    def __init__(self, model=None):
        import os
        self.model_name = model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        from langchain_openrouter import ChatOpenRouter
        self._client = ChatOpenRouter(model=self.model_name, temperature=0)

    def _raw_invoke(self, prompt: str) -> str:
        try:
            response = self._client.invoke(prompt)
        except Exception as e:
            raise LLMError(f"OpenRouter API call failed: {e}") from e
        text = response.content
        if isinstance(text, list):
            text = "".join(p if isinstance(p, str) else p.get("text", "") for p in text)
        return text

    def ask_json(self, prompt: str) -> dict:
        return _ask_json_with_retry(self._raw_invoke, prompt)


def get_provider() -> LLMProvider:
    """
    Selects the configured provider. Gemini is the default and is used
    unless LLM_PROVIDER is explicitly set to "openrouter" — there is no
    automatic fallback in either direction.
    """
    provider = (LLM_PROVIDER or "gemini").strip().lower()
    if provider == "gemini":
        return GeminiProvider()
    if provider == "openrouter":
        return OpenRouterProvider()
    raise LLMError(
        f"Unknown LLM_PROVIDER {provider!r}. Supported values: 'gemini' (default), 'openrouter'."
    )


_provider_singleton = None


def ask_llm_json(prompt):
    """
    Preserved entry point: every existing graph node calls this exact
    function, unchanged, regardless of which provider is configured.
    Lazily constructs and reuses one provider instance per process.
    """
    global _provider_singleton
    if _provider_singleton is None:
        _provider_singleton = get_provider()
    return _provider_singleton.ask_json(prompt)
