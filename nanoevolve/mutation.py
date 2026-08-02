from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .types import Evaluation


class InvalidModelResponse(ValueError):
    pass


class ModelRequestError(RuntimeError):
    pass


class _RetryableModelError(ModelRequestError):
    pass


class Model(Protocol):
    def generate(self, prompt: str) -> str:
        ...


def build_prompt(task: str, parent_source: str, evaluation: Evaluation) -> str:
    metrics = json.dumps(dict(evaluation.metrics), sort_keys=True)
    return (
        "You are a program mutation operator. Improve the parent program for the "
        "task below. Do not explain your reasoning. Return exactly one fenced Python "
        "code block containing the complete candidate source.\n\n"
        "## Task\n"
        f"{task.rstrip()}\n\n"
        "## Parent evaluation\n"
        f"Score: {evaluation.score}\n"
        f"Feedback: {evaluation.feedback}\n"
        f"Metrics: {metrics}\n\n"
        "## Parent source\n"
        "```python\n"
        f"{parent_source.rstrip()}\n"
        "```\n"
    )


_PYTHON_BLOCK = re.compile(r"```(?:python|py)[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_python_source(response: str) -> str:
    matches = _PYTHON_BLOCK.findall(response)
    if len(matches) != 1:
        raise InvalidModelResponse(
            f"expected exactly one fenced Python code block, found {len(matches)}"
        )
    source = matches[0].strip()
    if not source:
        raise InvalidModelResponse("Python code block is empty")
    return source + "\n"


@dataclass(frozen=True)
class OpenAICompatibleModel:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    timeout: float = 60.0
    max_retries: int = 2
    response_limit: int = 1024 * 1024

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model must not be empty")
        if not self.base_url:
            raise ValueError("base_url must not be empty")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.response_limit <= 0:
            raise ValueError("response_limit must be positive")

    def generate(self, prompt: str) -> str:
        request_body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._send(request)
            except (urllib.error.URLError, TimeoutError, _RetryableModelError) as error:
                last_error = error
                if attempt == self.max_retries:
                    break
                time.sleep(0.1 * (2**attempt))
        raise ModelRequestError(f"model request failed: {last_error}") from last_error

    def _send(self, request: urllib.request.Request) -> str:
        try:
            parsed = urllib.parse.urlparse(request.full_url)
            if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                response_context = opener.open(request, timeout=self.timeout)
            else:
                response_context = urllib.request.urlopen(request, timeout=self.timeout)
            with response_context as response:
                raw = response.read(self.response_limit + 1)
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", errors="replace")
            message = f"model HTTP {error.code}: {detail}"
            if error.code == 429 or error.code >= 500:
                raise _RetryableModelError(message) from error
            raise ModelRequestError(message) from error
        if len(raw) > self.response_limit:
            raise ModelRequestError("model response exceeded configured limit")
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise ModelRequestError("unsupported OpenAI-compatible response") from error
        if not isinstance(content, str):
            raise ModelRequestError("model response content must be a string")
        return content
