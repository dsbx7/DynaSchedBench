from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, List, TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_random_exponential

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from dsbx.Agents.LLMScheduler.config import ModelConfig


def _load_dotenv_if_present() -> None:
    """Best-effort .env loader to populate LLM-related environment variables.

    It loads .env files from a small set of candidate locations and sets any
    KEY=VALUE pairs into os.environ when the key is not defined *or* currently
    holds an empty string. This allows a project-local .env to provide
    defaults, while still letting explicitly non-empty environment variables
    win when present.
    """

    if os.getenv("DYNA_SCHEDBENCH_DISABLE_DOTENV"):
        return

    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd() / ".env")
    except Exception:
        pass
    try:
        here = Path(__file__).resolve()
        repo_root: Path | None = None
        for p in [here.parent, *here.parents]:
            if (p / "pyproject.toml").is_file():
                repo_root = p
                break
        if repo_root is not None:
            candidates.append(repo_root / ".env")
    except Exception:
        pass

    for path in candidates:
        try:
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if "=" not in s:
                        continue
                    key, val = s.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and (key not in os.environ or not os.environ.get(key)):
                        os.environ[key] = val
            logger.debug("llm_client: loaded .env from {}", path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("llm_client: failed to load .env from {}: {}", path, exc)

    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_dyna = bool(os.getenv("DYNA_SCHEDBENCH_LLM_API_KEY"))
    logger.debug(
        "llm_client: env after .env load: has OPENAI_API_KEY={} DYNA_SCHEDBENCH_LLM_API_KEY={}",
        has_openai,
        has_dyna,
    )


_load_dotenv_if_present()


def _truncate_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _append_llm_debug_record(record: dict[str, Any]) -> None:
    debug_dir = (os.getenv("DYNA_SCHEDBENCH_LLM_DEBUG_DIR") or "").strip()
    if not debug_dir:
        return
    try:
        path = Path(debug_dir) / "llm_calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str))
            f.write("\n")
    except Exception as exc:
        logger.debug("llm_client: failed to append llm debug record: {}", exc)


def _is_openai_compat_localish(base_url: str) -> bool:
    """Return True for localhost or private-network OpenAI-compatible servers.

    Supplementary scripts often target vLLM via addresses like
    ``http://10.x.x.x:8004/v1`` rather than ``127.0.0.1``. These endpoints
    should receive the same local-server treatment as localhost.
    """

    try:
        host = (urlparse(str(base_url)).hostname or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        return False
    if host in {"localhost", "::1"}:
        return True
    if host.startswith("127."):
        return True
    if host.startswith("10."):
        return True
    if host.startswith("192.168."):
        return True
    if host.endswith(".local"):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
            except Exception:
                second = -1
            if 16 <= second <= 31:
                return True
    return False


class LLMClient:
    """Abstract base class for LLM clients used by agents.

    Subclasses must implement :meth:`generate`, which returns a list of raw
    text completions given a prompt. The exact format of the returned strings
    is up to the caller; for LLMCoder they are expected to be JSON strings.
    """

    def generate(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = 0,
        timeout: float = 9999.0,
        **_: Any,
    ) -> List[str]:  # pragma: no cover - interface only
        raise NotImplementedError


class NullLLMClient(LLMClient):
    """Local stub that never performs external LLM calls.

    This client is used when no API key is configured or when the user wants
    to disable LLM-based behaviour while keeping the rest of the pipeline
    intact.
    """

    def generate(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = 0,
        timeout: float = 9999.0,
        **_: Any,
    ) -> List[str]:  # type: ignore[override]
        return []


class OpenAICompatClient(LLMClient):
    """Minimal OpenAI-compatible client using only the standard library.

    It targets the ``/chat/completions`` HTTP endpoint and expects a response
    with the usual ``{"choices": [{"message": {"content": "..."}}, ...]}``
    structure. Each ``content`` field is returned as one element of the
    result list.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        max_tokens: int | None = None,
        timeout: float = 9999.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must be a non-empty string")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        # Normalise max_tokens. For local OpenAI-compatible servers (such as
        # vLLM running on localhost), forcing a very large max_tokens can
        # easily exceed the model's context window and cause HTTP 400
        # BadRequest errors. In that case we deliberately avoid setting an
        # explicit max_tokens so that the server can choose a safe default.
        base_lower = self._base_url.lower()
        is_localish = _is_openai_compat_localish(self._base_url)
        if max_tokens is not None:
            if is_localish:
                # Local server: do not constrain max_tokens from the client
                # side; rely on the backend's own default limits instead.
                self._max_tokens = None
            else:
                try:
                    self._max_tokens = int(max_tokens)
                except (TypeError, ValueError):
                    self._max_tokens = None
        else:
            self._max_tokens = None
        self._default_timeout = float(timeout)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)

    @retry(wait=wait_random_exponential(min=10, max=20), stop=stop_after_attempt(2))
    def _call_api(
        self,
        messages: list[dict[str, str]],
        n: int,
        temperature: float,
        top_p: float,
        top_k: int,
        request_timeout: float,
        **extra: Any,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "n": max(1, int(n)),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "timeout": request_timeout,
        }

        max_tokens = extra.get("max_tokens")
        if max_tokens is not None:
            try:
                kwargs["max_tokens"] = int(max_tokens)
            except (TypeError, ValueError):
                pass

        if "dashscope.aliyuncs.com" in self._base_url:
            if isinstance(top_k, int) and top_k > 0:
                kwargs["top_k"] = int(top_k)

            extra_body = extra.get("extra_body") or {}
            if isinstance(extra_body, dict):
                extra_body.setdefault("enable_thinking", False)
                if extra_body:
                    kwargs["extra_body"] = extra_body
        else:
            base_lower = self._base_url.lower()
            model_lower = str(self._model).lower()
            is_local = _is_openai_compat_localish(self._base_url)
            if is_local and "qwen3" in model_lower:
                extra_body = extra.get("extra_body") or {}
                if isinstance(extra_body, dict):
                    chat_kwargs = extra_body.get("chat_template_kwargs") or {}
                    if isinstance(chat_kwargs, dict):
                        if "enable_thinking" not in chat_kwargs:
                            chat_kwargs["enable_thinking"] = False
                        extra_body["chat_template_kwargs"] = chat_kwargs
                    if extra_body:
                        kwargs["extra_body"] = extra_body

        return self._client.chat.completions.create(**kwargs)

    def generate(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = 0,
        timeout: float = 9999.0,
        **extra: Any,
    ) -> List[str]:  # type: ignore[override]
        started_at = time.time()
        count = max(1, int(n))
        if timeout is None:
            request_timeout = self._default_timeout
        else:
            try:
                request_timeout = float(timeout)
            except (TypeError, ValueError):
                request_timeout = self._default_timeout
        if self._default_timeout is not None:
            try:
                request_timeout = min(float(request_timeout), float(self._default_timeout))
            except (TypeError, ValueError):
                request_timeout = float(self._default_timeout)

        if "max_tokens" not in extra and self._max_tokens is not None:
            extra["max_tokens"] = int(self._max_tokens)

        messages = [
            {"role": "user", "content": prompt},
        ]

        # Debug-only: log request parameters (without sensitive data) to help
        # diagnose provider behaviour such as empty completions or length
        # limits. This intentionally omits the API key and prompt content.
        try:
            req_max_tokens = extra.get("max_tokens")
        except Exception:
            req_max_tokens = None
        logger.debug(
            "OpenAICompatClient debug: request params model={} base_url={} max_tokens={} temperature={} top_p={} top_k={} n={} timeout={}",
            self._model,
            self._base_url,
            req_max_tokens,
            temperature,
            top_p,
            top_k,
            count,
            request_timeout,
        )

        req_record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)),
            "ts_unix": started_at,
            "kind": "llm_call",
            "provider": "openai_compat",
            "model": self._model,
            "base_url": self._base_url,
            "request": {
                "n": count,
                "temperature": float(temperature),
                "top_p": float(top_p),
                "top_k": int(top_k),
                "timeout": request_timeout,
                "max_tokens": extra.get("max_tokens"),
                "response_format": extra.get("response_format"),
                "extra_body": extra.get("extra_body"),
            },
            "prompt": prompt,
            "prompt_preview": _truncate_text(prompt, limit=2000),
        }

        resp = None
        try:
            resp = self._call_api(
                messages,
                count,
                temperature,
                top_p,
                top_k,
                request_timeout,
                **extra,
            )
        except Exception as exc:  # pragma: no cover - network dependent
            if "response_format" in extra:
                try:
                    rf = extra.get("response_format")
                except Exception:
                    rf = None
                try:
                    extra2 = dict(extra)
                    extra2.pop("response_format", None)
                    logger.warning(
                        "OpenAICompatClient: request failed with response_format={}, retrying without response_format (error={})",
                        rf,
                        exc,
                    )
                    resp = self._call_api(
                        messages,
                        count,
                        temperature,
                        top_p,
                        top_k,
                        request_timeout,
                        **extra2,
                )
                except Exception as exc2:
                    logger.error("OpenAICompatClient API error: {}", exc2)
                    rec = dict(req_record)
                    rec["elapsed_sec"] = float(time.time() - started_at)
                    rec["error"] = repr(exc2)
                    rec["fallback_error"] = repr(exc)
                    _append_llm_debug_record(rec)
                    return []
            else:
                logger.error("OpenAICompatClient API error: {}", exc)
                rec = dict(req_record)
                rec["elapsed_sec"] = float(time.time() - started_at)
                rec["error"] = repr(exc)
                _append_llm_debug_record(rec)
                return []

        obj: Any
        try:
            obj = resp.model_dump()  # type: ignore[assignment]
        except Exception:
            obj = resp

        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("OpenAICompatClient: failed to parse string response as JSON: {}", exc)
                return []

        if not isinstance(obj, dict):
            logger.error("OpenAICompatClient: unexpected response type: {}", type(obj))
            return []

        usage = obj.get("usage") or {}
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            try:
                if pt is not None:
                    self.total_input_tokens += int(pt)
            except Exception:
                pass
            try:
                if ct is not None:
                    self.total_output_tokens += int(ct)
            except Exception:
                pass
            # Debug-only: log raw usage statistics to help understand token
            # budgeting and length-based truncation on provider side.
            logger.debug("OpenAICompatClient debug: usage={}", usage)

        choices = obj.get("choices") or []
        if not isinstance(choices, list):
            logger.error("OpenAICompatClient: response.choices is not a list")
            return []

        results: List[str] = []
        for ch in choices:
            if not isinstance(ch, dict):
                continue
            extracted = self._extract_choice_text(ch)
            if extracted:
                results.append(extracted)

        if not results:
            logger.warning("OpenAICompatClient: no valid message.content fields in response")
            logger.debug("OpenAICompatClient debug: raw choices={}", choices)

        rec = dict(req_record)
        rec["elapsed_sec"] = float(time.time() - started_at)
        rec["usage"] = usage if isinstance(usage, dict) else None
        rec["raw_response"] = obj
        rec["response_count"] = int(len(results))
        rec["responses"] = results
        rec["response_previews"] = [_truncate_text(x, limit=2000) for x in results]
        _append_llm_debug_record(rec)

        return results

    @staticmethod
    def _extract_choice_text(choice: dict[str, Any]) -> str:
        """Best-effort extraction for OpenAI-compatible chat responses.

        Different providers may return assistant content as:
        - ``message.content`` plain string;
        - ``message.content`` list of typed content parts;
        - legacy ``text`` field on the choice;
        - provider-specific fields such as ``output_text``.
        """

        if not isinstance(choice, dict):
            return ""

        direct_text = OpenAICompatClient._coerce_text_payload(choice.get("text"))
        if direct_text:
            return direct_text

        msg = choice.get("message") or {}
        if not isinstance(msg, dict):
            return ""

        content_text = OpenAICompatClient._coerce_text_payload(msg.get("content"))
        if content_text:
            return content_text

        for key in ("output_text", "text", "reasoning_content"):
            alt = OpenAICompatClient._coerce_text_payload(msg.get(key))
            if alt:
                return alt

        refusal = msg.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            return refusal

        return ""

    @staticmethod
    def _coerce_text_payload(payload: Any) -> str:
        """Flatten common OpenAI-compatible content payload shapes into text."""

        if isinstance(payload, str):
            return payload.strip()

        if isinstance(payload, list):
            parts: list[str] = []
            for item in payload:
                text = OpenAICompatClient._coerce_text_payload(item)
                if text:
                    parts.append(text)
            return "".join(parts).strip()

        if isinstance(payload, dict):
            for key in ("text", "output_text", "content", "value"):
                if key in payload:
                    text = OpenAICompatClient._coerce_text_payload(payload.get(key))
                    if text:
                        return text

            nested = payload.get("refusal")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()

        return ""


class RetryingLLMClient(LLMClient):
    def __init__(self, base: LLMClient, max_retries: int = 3, backoff: float = 1.0) -> None:
        self._base = base
        self._max_retries = int(max(1, max_retries))
        self._backoff = float(backoff)

    def generate(
        self,
        prompt: str,
        n: int = 1,
        temperature: float = 0.0,
        top_p: float = 1.0,
        top_k: int = 0,
        timeout: float = 9999.0,
        **extra: Any,
    ) -> List[str]:  # type: ignore[override]
        for attempt in range(self._max_retries):
            out = self._base.generate(
                prompt,
                n=n,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                timeout=timeout,
                **extra,
            )
            if out:
                return out
            if attempt + 1 < self._max_retries:
                delay = self._backoff * (attempt + 1)
                try:
                    time.sleep(delay)
                except Exception:  # pragma: no cover - defensive
                    break
        return []


def resolve_llm_endpoint(provider: str, base_url_override: str | None = None) -> tuple[str, str]:
    prov = (provider or "openai").lower()
    if base_url_override is None:
        env_base = os.getenv("DYNA_SCHEDBENCH_LLM_BASE_URL")
        if env_base:
            base_url_override = env_base
    if prov in ("openai", "openai_compat", "compat"):
        api_key = os.getenv("DYNA_SCHEDBENCH_LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = base_url_override or "https://api.openai.com/v1"
    elif prov in ("dashscope", "aliyun"):
        api_key = os.getenv("DASHSCOPE_API_KEY", "") or os.getenv("DYNA_SCHEDBENCH_LLM_API_KEY", "")
        base_url = base_url_override or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif prov in ("chatanywhere",):
        api_key = os.getenv("OPENAI_API_KEY", "") or os.getenv("DYNA_SCHEDBENCH_LLM_API_KEY", "")
        base_url = base_url_override or "https://api.chatanywhere.tech/v1"
    elif prov in ("local", "vllm", "openai_local"):
        api_key = os.getenv("OPENAI_API_KEY", "EMPTY") or "EMPTY"
        base_url = base_url_override or "http://localhost:8000/v1"
    else:
        api_key = os.getenv("DYNA_SCHEDBENCH_LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = base_url_override or "https://api.openai.com/v1"
    return api_key, base_url
