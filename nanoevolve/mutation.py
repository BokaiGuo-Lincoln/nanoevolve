from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Mapping, Protocol, Sequence

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


def _safe_path(value: str) -> str:
    path = PurePosixPath(value.strip())
    if not value.strip() or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise InvalidModelResponse(f"unsafe workspace path: {value!r}")
    return path.as_posix()


def build_prompt(
    task: str,
    parent_source: str,
    evaluation: Evaluation,
    *,
    mutation_mode: str = "full",
    inspirations: Sequence[tuple[str, str, Evaluation]] = (),
    artifact_feedback: Mapping[str, str] | None = None,
    multi_file: bool = False,
) -> str:
    metrics = json.dumps(dict(evaluation.metrics), sort_keys=True)
    instructions = {
        "full": "Return exactly one fenced Python code block containing the complete candidate source.",
        "search_replace": (
            "Return one or more exact SEARCH/REPLACE blocks. Each block must contain "
            "a 'path: relative/path.py' line, SEARCH text, =======, replacement text, "
            "and >>>>>>> REPLACE."
        ),
        "evolve_blocks": (
            "Return one or more named EVOLVE blocks using <<<<<<< EVOLVE name, the "
            "replacement body, and >>>>>>> EVOLVE."
        ),
    }
    try:
        instruction = instructions[mutation_mode]
    except KeyError as error:
        raise ValueError(f"unknown mutation mode: {mutation_mode}") from error
    if mutation_mode == "full" and multi_file:
        instruction = (
            "Return the complete workspace as one or more sections formatted as "
            "'### FILE: relative/path.py' followed by one fenced code block. Files "
            "omitted from the response are deleted."
        )
    prompt = (
        "You are a program mutation operator. Improve the parent program for the "
        f"task below. Do not explain your reasoning. {instruction}\n\n"
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
    if inspirations:
        prompt += "\n## Inspiration candidates\n"
        for record_id, source, inspiration_evaluation in inspirations:
            prompt += (
                f"### {record_id}\nScore: {inspiration_evaluation.score}\n"
                f"```python\n{source.rstrip()}\n```\n"
            )
    if artifact_feedback:
        prompt += "\n## Artifact feedback\n"
        for name, content in sorted(artifact_feedback.items()):
            prompt += f"### {name}\n```text\n{content.rstrip()}\n```\n"
    return prompt


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


_FILE_BLOCK = re.compile(
    r"^### FILE:[ \t]*(.+?)[ \t]*\r?\n```(?:python|py|text)?[ \t]*\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)


def extract_workspace(response: str, default_path: str) -> dict[str, str]:
    matches = _FILE_BLOCK.findall(response)
    if not matches:
        return {_safe_path(default_path): extract_python_source(response)}
    workspace: dict[str, str] = {}
    for raw_path, raw_content in matches:
        path = _safe_path(raw_path)
        if path in workspace:
            raise InvalidModelResponse(f"duplicate workspace path: {path}")
        workspace[path] = raw_content.strip() + "\n"
    return workspace


_SEARCH_REPLACE = re.compile(
    r"<<<<<<< SEARCH\r?\npath:[ \t]*(.+?)[ \t]*\r?\n(.*?)=======\r?\n(.*?)>>>>>>> REPLACE",
    re.DOTALL,
)


def apply_search_replace(
    parent: Mapping[str, str], response: str
) -> dict[str, str]:
    matches = _SEARCH_REPLACE.findall(response)
    if not matches:
        raise InvalidModelResponse("expected at least one SEARCH/REPLACE block")
    candidate = dict(parent)
    for raw_path, search, replacement in matches:
        path = _safe_path(raw_path)
        if path not in candidate:
            if search:
                raise InvalidModelResponse(f"cannot search missing file: {path}")
            candidate[path] = replacement
            continue
        occurrences = candidate[path].count(search)
        if not search or occurrences != 1:
            raise InvalidModelResponse(
                f"SEARCH text for {path} must occur exactly once, found {occurrences}"
            )
        if replacement == "" and candidate[path] == search:
            del candidate[path]
        else:
            candidate[path] = candidate[path].replace(search, replacement, 1)
    if not candidate:
        raise InvalidModelResponse("mutation deleted the entire workspace")
    return candidate


_EVOLVE_RESPONSE = re.compile(
    r"<<<<<<< EVOLVE[ \t]+([^\r\n]+)\r?\n(.*?)>>>>>>> EVOLVE",
    re.DOTALL,
)
_EVOLVE_REGION = re.compile(
    r"(?P<start>^[ \t]*#[ \t]*EVOLVE-BLOCK:[ \t]*(?P<name>[^\r\n]+?)[ \t]+START[ \t]*$\r?\n)"
    r"(?P<body>.*?)"
    r"(?P<end>^[ \t]*#[ \t]*EVOLVE-BLOCK:[ \t]*(?P=name)[ \t]+END[ \t]*$)",
    re.DOTALL | re.MULTILINE,
)


def apply_evolve_blocks(parent: Mapping[str, str], response: str) -> dict[str, str]:
    replacements = _EVOLVE_RESPONSE.findall(response)
    if not replacements:
        raise InvalidModelResponse("expected at least one EVOLVE block")
    requested: dict[str, str] = {}
    for raw_name, body in replacements:
        name = raw_name.strip()
        if not name or name in requested:
            raise InvalidModelResponse(f"duplicate or empty EVOLVE block: {name!r}")
        requested[name] = body
    found: dict[str, tuple[str, re.Match[str]]] = {}
    for path, source in parent.items():
        for match in _EVOLVE_REGION.finditer(source):
            name = match.group("name").strip()
            if name in found:
                raise InvalidModelResponse(f"duplicate EVOLVE-BLOCK marker: {name}")
            found[name] = (path, match)
    missing = sorted(set(requested) - set(found))
    if missing:
        raise InvalidModelResponse("unknown EVOLVE blocks: " + ", ".join(missing))
    candidate = dict(parent)
    by_path: dict[str, list[tuple[re.Match[str], str]]] = {}
    for name, body in requested.items():
        path, match = found[name]
        by_path.setdefault(path, []).append((match, body))
    for path, changes in by_path.items():
        source = candidate[path]
        for match, body in sorted(changes, key=lambda item: item[0].start(), reverse=True):
            replacement = match.group("start") + body + match.group("end")
            source = source[: match.start()] + replacement + source[match.end() :]
        candidate[path] = source
    return candidate


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
