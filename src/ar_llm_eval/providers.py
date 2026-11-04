"""Minimal LLM provider layer (no SDKs, only ``httpx``).

A model is addressed as ``<provider>:<model>``:

==============  ==========================================================
``openai``      any OpenAI-compatible chat API (``OPENAI_API_KEY``, ``OPENAI_BASE_URL``)
``openrouter``  OpenRouter (``OPENROUTER_API_KEY``)
``groq``        Groq (``GROQ_API_KEY``)
``ollama``      local Ollama at ``OLLAMA_BASE_URL`` (default ``http://localhost:11434/v1``)
``lmstudio``    local LM Studio at ``LMSTUDIO_BASE_URL`` (default ``http://localhost:1234/v1``)
``anthropic``   Anthropic Messages API (``ANTHROPIC_API_KEY``)
``mock``        offline, deterministic *simulated* models (tests and demos)
==============  ==========================================================

Mock models never call a language model. They build an answer from the
item's hand-written reference and then damage it in an Arabic-specific way.
Every result they produce is flagged ``mock: true`` and the leaderboard shows
it as DEMO. They exist to exercise the runner, graders and leaderboard only.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .normalize import strip_diacritics


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class Completion:
    text: str
    latency_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


def load_dotenv(path: str = ".env") -> None:
    """Tiny ``.env`` reader: ``KEY=value`` lines; existing env vars win."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def _post(url: str, *, headers: dict, payload: dict, timeout: float, retries: int) -> dict:
    import httpx

    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        except httpx.HTTPError as e:  # network errors are retried
            last = ProviderError(f"{type(e).__name__}: {e}")
        else:
            if r.status_code < 400:
                return r.json()
            err = ProviderError(f"HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code not in (408, 409, 425, 429) and r.status_code < 500:
                raise err  # bad key / unknown model: retrying will not help
            last = err
        if attempt < retries:
            time.sleep(delay)
            delay = min(delay * 2, 30)
    assert last is not None
    raise last


class OpenAICompatible:
    is_mock = False

    def __init__(self, name: str, model: str, base_url: str, api_key: str | None, *,
                 timeout: float = 120, retries: int = 3, extra_headers: dict | None = None):
        self.name, self.model = name, model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout, self.retries = timeout, retries
        self.extra_headers = extra_headers or {}

    def complete(self, messages: list[Message], *, temperature: float = 0.0, max_tokens: int = 1024,
                 item: Any = None) -> Completion:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        t0 = time.perf_counter()
        data = _post(f"{self.base_url}/chat/completions", headers=headers, payload=payload,
                     timeout=self.timeout, retries=self.retries)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"unexpected response shape: {str(data)[:300]}") from e
        return Completion(text=text, latency_s=time.perf_counter() - t0, usage=data.get("usage") or {})


class Anthropic:
    is_mock = False

    def __init__(self, model: str, api_key: str, *, base_url: str = "https://api.anthropic.com",
                 timeout: float = 120, retries: int = 3):
        self.name, self.model = "anthropic", model
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.timeout, self.retries = timeout, retries

    def complete(self, messages: list[Message], *, temperature: float = 0.0, max_tokens: int = 1024,
                 item: Any = None) -> Completion:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
        }
        if system:
            payload["system"] = system
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        t0 = time.perf_counter()
        data = _post(f"{self.base_url}/v1/messages", headers=headers, payload=payload,
                     timeout=self.timeout, retries=self.retries)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return Completion(text=text, latency_s=time.perf_counter() - t0, usage=data.get("usage") or {})


# --- mock (simulated) models ------------------------------------------------

# Gulf -> MSA substitutions used by ``mock:msa-only`` to simulate a model that
# understands the question but cannot answer in dialect.
_GULF_TO_MSA = {
    "الحين": "الآن", "وايد": "كثيراً", "شو": "ماذا", "ليش": "لماذا", "وين": "أين",
    "أبا": "أريد", "ابا": "أريد", "أبي": "أريد", "ابي": "أريد", "باچر": "غداً", "باكر": "غداً",
    "مب": "ليس", "هب": "ليس", "زين": "جيد", "خوش": "جيد", "يالس": "جالس", "عيل": "إذن",
    "هيه": "نعم", "إيه": "نعم", "شلون": "كيف", "شحالك": "كيف حالك", "عسب": "لكي",
    "تراه": "إنه", "ترى": "إن", "بروح": "سأذهب", "بسير": "سأذهب", "سير": "اذهب",
    "واجد": "كثيراً", "يبا": "يريد", "نبا": "نريد", "بعدين": "لاحقاً", "حق": "لـ",
}
_MOCK_KINDS = ("oracle", "echo", "random", "no-diacritics", "msa-only")


class Mock:
    """Simulated model. ``mock:<kind>`` with kind one of:

    ``oracle``         returns the hand-written reference (upper bound sanity check)
    ``echo``           repeats the prompt (lower bound)
    ``random``         random option for multiple choice, prompt echo otherwise
    ``no-diacritics``  reference with all tashkeel removed
    ``msa-only``       reference with Gulf words replaced by MSA equivalents
    ``noisy-<pct>``    on ``pct``% of items (seeded by item id) gives a wrong
                       option / drops diacritics / echoes; otherwise oracle
    Kinds can be chained with ``+``: ``mock:no-diacritics+noisy-20``.
    """

    is_mock = True

    def __init__(self, spec: str, seed: int = 0):
        self.name, self.model, self.seed = "mock", spec, seed
        self.kinds = [k.strip() for k in spec.split("+") if k.strip()]
        if not self.kinds:
            raise ProviderError("mock model needs a kind, e.g. mock:oracle")
        for k in self.kinds:
            if k not in _MOCK_KINDS and not re.fullmatch(r"noisy-\d{1,3}", k):
                raise ProviderError(f"unknown mock kind {k!r}; choose from {', '.join(_MOCK_KINDS)}, noisy-<pct>")

    def _rng(self, item_id: str, salt: str) -> random.Random:
        h = hashlib.sha256(f"{self.seed}:{self.model}:{salt}:{item_id}".encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def complete(self, messages: list[Message], *, temperature: float = 0.0, max_tokens: int = 1024,
                 item: Any = None) -> Completion:
        prompt = messages[-1].content if messages else ""
        if item is None:
            return Completion(text=prompt)
        ref = item.reference or ""
        options = list((item.options or {}).keys())
        text = ref
        for kind in self.kinds:
            if kind == "oracle":
                text = ref
            elif kind == "echo":
                text = prompt
            elif kind == "random":
                rng = self._rng(item.id, "random")
                text = rng.choice(options) if options else prompt
            elif kind == "no-diacritics":
                text = strip_diacritics(text)
            elif kind == "msa-only":
                if item.dialect == "gulf":
                    for g, m in _GULF_TO_MSA.items():
                        text = re.sub(rf"(?<![\w]){g}(?![\w])", m, text)
            elif kind.startswith("noisy-"):
                pct = int(kind.split("-", 1)[1])
                rng = self._rng(item.id, kind)
                if rng.random() * 100 < pct:
                    if options:
                        wrong = [o for o in options if o != (item.reference or "").strip()]
                        text = rng.choice(wrong or options)
                    elif item.category == "diacritics":
                        text = strip_diacritics(text)
                    else:
                        text = prompt
        return Completion(text=text, latency_s=0.0, usage={})


# --- factory ----------------------------------------------------------------

_OPENAI_LIKE = {
    "openai": ("OPENAI_BASE_URL", "https://api.openai.com/v1", "OPENAI_API_KEY", True),
    "openrouter": ("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", True),
    "groq": ("GROQ_BASE_URL", "https://api.groq.com/openai/v1", "GROQ_API_KEY", True),
    "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434/v1", None, False),
    "lmstudio": ("LMSTUDIO_BASE_URL", "http://localhost:1234/v1", None, False),
}
PROVIDERS = (*_OPENAI_LIKE, "anthropic", "mock")


def parse_model_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ProviderError(f"model must look like <provider>:<model>, got {spec!r}")
    provider, model = spec.split(":", 1)
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise ProviderError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
    if not model.strip():
        raise ProviderError("empty model name")
    return provider, model.strip()


def get_provider(spec: str, *, timeout: float | None = None, retries: int | None = None, seed: int = 0):
    provider, model = parse_model_spec(spec)
    timeout = float(timeout if timeout is not None else os.getenv("AR_EVAL_TIMEOUT", 120))
    retries = int(retries if retries is not None else os.getenv("AR_EVAL_RETRIES", 3))
    if provider == "mock":
        return Mock(model, seed=seed)
    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        return Anthropic(model, key, base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                         timeout=timeout, retries=retries)
    url_env, default_url, key_env, needs_key = _OPENAI_LIKE[provider]
    key = os.getenv(key_env) if key_env else None
    if needs_key and not key:
        raise ProviderError(f"{key_env} is not set")
    extra = {}
    if provider == "openrouter":
        extra = {"HTTP-Referer": "https://github.com/mohammadhadijavidi/ar-llm-eval", "X-Title": "ar-llm-eval"}
    return OpenAICompatible(provider, model, os.getenv(url_env, default_url), key,
                            timeout=timeout, retries=retries, extra_headers=extra)
