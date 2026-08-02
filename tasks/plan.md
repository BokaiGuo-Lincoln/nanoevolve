# Implementation Plan: NanoEvolve v0.1

## Overview

Implement the approved NanoEvolve v0.1 specification as a zero-runtime-dependency Python 3.11 package. Development follows test-driven slices: define public behavior in `unittest`, verify the test fails for the intended reason, add the smallest production implementation, and keep the complete suite green after each slice.

## Architecture Decisions

- Keep six semantic modules: `types`, `mutation`, `archive`, `runner`, `engine`, and `cli`.
- Export only `evolve`, core records/events, and `OpenAICompatibleModel`.
- Persist mutable state only in append-only `records.jsonl` plus immutable artifact directories.
- Derive deterministic per-generation randomness with SHA-256.
- Treat every mutation attempt as one generation, including failures.
- Run evaluators in fresh subprocesses and describe this as fault isolation, not sandboxing.
- Use standard-library `unittest`, HTTP, CLI, JSON, and subprocess APIs.

## Dependency Graph

```text
types
  ├── mutation
  ├── archive
  └── runner
        └── engine
              └── cli + examples
```

## Task List

### Phase 1: Package Foundation

- [x] Task 1: Add packaging and public data types.
- [x] Task 2: Add full-source extraction and OpenAI-compatible model client.

### Checkpoint: Foundation

- [x] Type and mutation tests pass.
- [x] Package imports without third-party dependencies.

### Phase 2: Durable Execution Primitives

- [x] Task 3: Add JSONL archive, artifact commits, recovery, and deterministic selection.
- [x] Task 4: Add evaluator normalization and subprocess runner failure mapping.

### Checkpoint: Primitives

- [x] Archive recovery and selection tests pass.
- [x] Runner success, error, invalid result, and timeout tests pass.

### Phase 3: End-to-End Evolution

- [x] Task 5: Add the sequential `evolve()` loop and runtime events.
- [x] Task 6: Add `run`, `resume`, `best`, and `inspect` commands.

### Checkpoint: Core Flow

- [x] Mock-model evolution improves a deterministic example.
- [x] Interrupted state can resume without overwriting records.
- [x] All four CLI commands pass integration tests.

### Phase 4: Release Surface

- [x] Task 7: Add README and deterministic/real-model examples.
- [x] Task 8: Run the complete test suite and manual CLI smoke checks.

### Checkpoint: Complete

- [x] All tests pass without warnings.
- [x] Package installs and imports in a clean temporary environment.
- [x] README quick start matches the implemented CLI.
- [x] No third-party runtime dependency is declared.

## Detailed Tasks

### Task 1: Package and public types

**Description:** Create package metadata and immutable public records that define evaluation, record status, records, and runtime events.

**Acceptance criteria:**
- [x] `Evaluation`, `Record`, and `EvolutionEvent` are immutable dataclasses.
- [x] Evaluation validates finite numeric scores and metrics.
- [x] Public imports match the approved specification.

**Verification:**
- [x] `python -m unittest tests.test_types -v`

**Dependencies:** None

**Files likely touched:** `pyproject.toml`, `nanoevolve/__init__.py`, `nanoevolve/types.py`, `tests/test_types.py`

**Estimated scope:** Medium

### Task 2: Mutation boundary

**Description:** Implement exact prompt construction, unambiguous full-source extraction, and a non-streaming OpenAI-compatible HTTP client with bounded retries and response limits.

**Acceptance criteria:**
- [x] Prompt contains task, parent source, evaluation context, and no hidden system message.
- [x] Exactly one Python code block is accepted; missing or ambiguous blocks fail.
- [x] HTTP requests use one user message and normalize API errors.

**Verification:**
- [x] `python -m unittest tests.test_mutation -v`

**Dependencies:** Task 1

**Files likely touched:** `nanoevolve/mutation.py`, `tests/test_mutation.py`

**Estimated scope:** Medium

### Task 3: Archive and selection

**Description:** Implement run metadata, append-only records, immutable artifact commits, tail recovery, integrity checks, best-record lookup, and deterministic top-k/epsilon selection.

**Acceptance criteria:**
- [x] Records survive reopen and only a truncated final line is recoverable.
- [x] Candidate artifacts are committed before their JSONL record becomes visible.
- [x] Parent selection is reproducible for a run seed and generation.

**Verification:**
- [x] `python -m unittest tests.test_archive -v`

**Dependencies:** Task 1

**Files likely touched:** `nanoevolve/archive.py`, `tests/test_archive.py`

**Estimated scope:** Medium

### Task 4: Evaluator runner

**Description:** Normalize evaluator return forms and execute importable top-level evaluator functions in a fresh process with temporary files, filtered secrets, timeout, and output capture.

**Acceptance criteria:**
- [x] Float, dict, and `Evaluation` returns normalize correctly.
- [x] Exceptions, timeouts, invalid results, and oversized output map to explicit statuses.
- [x] Evaluator credentials matching the fixed secret-name rule are removed.

**Verification:**
- [x] `python -m unittest tests.test_runner -v`

**Dependencies:** Task 1

**Files likely touched:** `nanoevolve/runner.py`, `tests/test_runner.py`, `tests/fixtures/evaluators.py`

**Estimated scope:** Medium

### Task 5: Evolution engine

**Description:** Join selection, mutation, runner, and archive commits into the sequential `evolve()` API while preserving failures and emitting runtime events.

**Acceptance criteria:**
- [x] Seed generation is evaluated once as generation 0.
- [x] Every attempted mutation produces a committed record.
- [x] Resume targets a total generation and does not duplicate completed work.

**Verification:**
- [x] `python -m unittest tests.test_engine -v`

**Dependencies:** Tasks 2-4

**Files likely touched:** `nanoevolve/engine.py`, `tests/test_engine.py`

**Estimated scope:** Medium

### Task 6: CLI

**Description:** Expose project-driven run, resume, best, and inspect commands with JSON output where specified.

**Acceptance criteria:**
- [x] `run` refuses existing state and validates project files.
- [x] `resume` is idempotent at the requested target generation.
- [x] `best` and `inspect` return human-readable and machine-readable data.

**Verification:**
- [x] `python -m unittest tests.test_cli -v`

**Dependencies:** Task 5

**Files likely touched:** `nanoevolve/cli.py`, `tests/test_cli.py`

**Estimated scope:** Medium

### Task 7: Documentation and examples

**Description:** Add an executable deterministic quick start and a circle-packing template, then document the API, CLI, archive format, and security boundary.

**Acceptance criteria:**
- [x] Quick start works without a network request.
- [x] Real-model example is clearly marked as a manual smoke path.
- [x] README does not claim hostile-code sandboxing or AlphaEvolve parity.

**Verification:**
- [x] Run the deterministic example through all four CLI commands.

**Dependencies:** Task 6

**Files likely touched:** `README.md`, `examples/hello_evolve/*`, `examples/circle_packing/*`

**Estimated scope:** Medium

### Task 8: Release verification

**Description:** Run focused and complete tests, compile the package, install it into an isolated temporary environment, and verify the documented CLI surface.

**Acceptance criteria:**
- [x] Complete `unittest` discovery passes.
- [x] `compileall` passes.
- [x] Clean install has no third-party runtime dependency.

**Verification:**
- [x] `python -m unittest discover -s tests -v`
- [x] `python -m compileall nanoevolve examples`
- [x] Temporary virtual-environment install and import smoke.

**Dependencies:** Tasks 1-7

**Files likely touched:** None unless verification exposes a defect.

**Estimated scope:** Small

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Subprocess evaluator import semantics differ across platforms | High | Require top-level importable functions and cover subprocess behavior in integration tests. |
| Partial artifact or JSONL writes corrupt resume | High | Use temporary directories, atomic rename, fsync, and strict middle-line corruption errors. |
| OpenAI-compatible endpoints vary subtly | Medium | Keep the client intentionally narrow and test the exact supported response schema. |
| CLI and Python API drift | Medium | Route CLI through the same `evolve()` implementation and test both paths. |
| Security claims exceed implementation | High | Keep explicit fault-isolation language in code errors and README. |
| Zero-dependency goal creates excessive HTTP complexity | Low | Support only non-streaming JSON requests and defer advanced provider behavior. |

## Open Questions

None. The approved design resolves the v0.1 scope and behavior.
