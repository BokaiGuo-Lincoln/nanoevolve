# NanoEvolve Design Specification

Date: 2026-08-02

Status: Approved design

## 1. Product Definition

NanoEvolve is a minimal, observable, and composable program-evolution loop that treats an LLM as a mutation operator.

Its product position is:

> The smallest useful evolutionary programming loop.

The Chinese description is:

> 一个透明、可恢复、没有隐藏工作流的 LLM 程序进化内核。

NanoEvolve does not attempt to reproduce OpenEvolve feature by feature. It extracts the smallest useful computation model shared by AlphaEvolve-style systems:

```text
select -> mutate -> evaluate -> archive
```

The evolution engine, rather than the model, owns control flow. The model cannot call tools, modify files directly, create sub-agents, plan the run, or decide when evolution stops.

## 2. Design Principles

The first release follows these principles:

1. Prefer ordinary functions over framework abstractions.
2. Keep prompts and state fully visible on disk.
3. Use append-only records instead of a database.
4. Keep the engine sequential and deterministic.
5. Preserve every mutation attempt, including failures.
6. Separate semantic modules without exposing an object graph to users.
7. Add quality-diversity mechanisms only after a demonstrated need.
8. Do not claim that subprocess execution is a security sandbox.

The codebase should be small because it contains few concepts, not because unrelated responsibilities are compressed into large files.

## 3. Scope

### 3.1 Included in v0.1

- One Python source file per candidate.
- One parent per mutation attempt.
- Full-source model output.
- OpenAI-compatible, non-streaming model requests.
- Append-only JSONL records.
- Immutable candidate artifact directories.
- Top-k selection with epsilon exploration.
- Evaluator execution in a fresh subprocess.
- Timeout, output truncation, and temporary-directory cleanup.
- Deterministic per-generation random seeds.
- Run, resume, best, and inspect CLI commands.
- Runtime events through an optional callback.
- Zero third-party runtime dependencies.

### 3.2 Explicitly excluded from v0.1

- SEARCH/REPLACE patch mutation.
- EVOLVE-BLOCK markers.
- Inspiration candidates.
- MAP-Elites.
- Islands and migration.
- Multi-objective Pareto selection.
- Parallel generation or evaluation.
- Multi-file workspaces and Git worktrees.
- SQLite or another database.
- Artifact feedback channels.
- Provider registries.
- Plugin or observer registries.
- LLM-as-judge evaluation.
- Automatic evaluator generation.
- Prompt evolution.
- Docker SDK integration.
- A TUI, Web UI, cloud control plane, MCP, planning, sub-agents, or long-term memory.

## 4. User Experience

### 4.1 Experiment layout

A user experiment contains three files:

```text
my-experiment/
├── TASK.md
├── seed.py
└── evaluate.py
```

`TASK.md` contains the goal, optimization objective, and constraints. It is supplied to the model verbatim.

`seed.py` contains the initial candidate.

`evaluate.py` defines the evaluator contract.

### 4.2 Python API

The primary API is:

```python
best = evolve(
    seed="seed.py",
    evaluate=evaluate,
    model=model,
    task="TASK.md",
    iterations=100,
    workdir=".nanoevolve",
    random_seed=42,
    timeout=30,
    on_event=None,
)
```

`evolve()` returns the best successful `Record`.

The `evaluate` argument must be a top-level function defined in an importable Python file. NanoEvolve resolves that function's source module and imports the same function inside the evaluator subprocess. Lambdas, closures, bound methods, and interactive-only functions are rejected with a clear configuration error.

The public package exports only:

```text
evolve
Evaluation
Record
EvolutionEvent
OpenAICompatibleModel
```

The archive implementation, selection functions, runner worker, prompt builder, and response parser are internal APIs in v0.1.

### 4.3 CLI

NanoEvolve exposes four commands.

#### Run

```bash
nanoevolve run . \
  --model gpt-5-mini \
  --iterations 100 \
  --random-seed 42
```

`run` validates the project, refuses to overwrite an existing `.nanoevolve/` directory, evaluates the seed as generation 0, and then performs mutation generations 1 through 100.

The seed does not consume a mutation generation.

#### Resume

```bash
nanoevolve resume . --iterations 200
```

The `--iterations` value is the desired total mutation generation, not an additional count. If the archive already contains generation 73, the command executes generations 74 through 200. Repeating the same command after generation 200 performs no new mutations.

When `--iterations` is omitted, `resume` uses the initial target stored in `run.json`.

#### Best

```bash
nanoevolve best .
```

The command prints the best record ID, score, generation, parent, and source path. A `--json` option returns a machine-readable representation.

#### Inspect

```bash
nanoevolve inspect . <record-id>
```

The command shows lineage, selection metadata, evaluation results, failure information, and paths to the prompt, model response, candidate source, stdout, and stderr. Large artifacts are not dumped by default.

### 4.4 Model configuration

Model configuration can be supplied through CLI flags or environment variables:

```text
--model       NANOEVOLVE_MODEL
--base-url    NANOEVOLVE_BASE_URL
--api-key     NANOEVOLVE_API_KEY
```

CLI flags take precedence. NanoEvolve does not introduce YAML or TOML run configuration in v0.1.

## 5. Core Data Model

### 5.1 Evaluation

```python
@dataclass(frozen=True)
class Evaluation:
    score: float
    feedback: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
```

`score` is the only optimization target in v0.1. Metrics are recorded for inspection but do not affect selection.

### 5.2 Record status

```python
RecordStatus = Literal[
    "success",
    "model_error",
    "invalid_response",
    "evaluation_error",
    "evaluation_timeout",
    "invalid_evaluation",
]
```

### 5.3 Record

```python
@dataclass(frozen=True)
class Record:
    id: str
    parent_id: str | None
    generation: int
    status: RecordStatus
    source_path: str | None
    evaluation: Evaluation | None
    error: str | None
```

A `Record` represents one completed mutation attempt. It may lack source and evaluation artifacts if the model request failed or did not return a valid candidate.

There is no separate `Candidate` and `Program` type in v0.1.

### 5.4 Evolution event

```python
@dataclass(frozen=True)
class EvolutionEvent:
    type: str
    generation: int
    record_id: str | None
    data: dict[str, object]
```

Events are runtime notifications used by the CLI or callers. They do not form a second persistent state database.

### 5.5 Model protocol

```python
class Model(Protocol):
    def generate(self, prompt: str) -> str:
        ...
```

The default implementation is `OpenAICompatibleModel`. v0.1 does not include a provider adapter registry.

## 6. Evolution Control Flow

The engine executes this sequence for each generation:

```text
load archive view
      |
      v
select one parent
      |
      v
build complete visible prompt
      |
      v
call Model.generate()
      |
      v
extract complete candidate source
      |
      v
run evaluator subprocess
      |
      v
commit immutable artifacts and JSONL record
      |
      v
emit runtime event
```

The engine is sequential. A later version may parallelize evaluation, but a single engine remains responsible for selection and archive commits.

Each mutation attempt consumes one generation, including model failures, invalid responses, evaluator crashes, timeouts, and invalid evaluator results. This prevents infinite retry loops and keeps generation numbers aligned with mutation attempts and cost accounting.

Transient model transport failures may be retried at most twice within the same generation. Raw request outcomes are preserved in the generation artifacts.

## 7. Mutation Contract

### 7.1 Prompt contents

The v0.1 prompt contains only:

1. The complete `TASK.md` text.
2. The complete parent source.
3. The parent's score, feedback, and metrics.
4. The required full-source response format.

The prompt does not include archive history, inspiration candidates, generated summaries, hidden domain instructions, judge feedback, or a dynamic strategy prompt.

`OpenAICompatibleModel` sends this content as one user message and does not add a hidden system message.

The exact model input is saved as `prompt.txt`.

### 7.2 Response format

The model must return one Python code block containing the complete candidate source:

````text
```python
def solve(...):
    ...
```
````

Text outside the code block is preserved in `response.txt` but is not executed.

Responses with no unambiguous Python code block receive `invalid_response` status.

Full-source output is intentional in v0.1. SEARCH/REPLACE patch parsing is deferred because it adds matching ambiguity and additional failure modes without being necessary for a single-file candidate.

## 8. Module Architecture

The package contains six internal semantic modules:

```text
nanoevolve/
├── __init__.py
├── types.py
├── engine.py
├── mutation.py
├── archive.py
├── runner.py
└── cli.py
```

`__init__.py` only exports the public API and is not counted as an internal semantic module.

### 8.1 types.py

- Defines `Evaluation`, `Record`, `EvolutionEvent`, `RecordStatus`, and small type aliases.
- Contains no orchestration, storage, HTTP, or subprocess logic.

### 8.2 engine.py

- Implements `evolve()`.
- Owns generation sequencing.
- Calls selection, mutation, evaluation, and archive commit functions.
- Emits runtime events.
- Does not send HTTP requests or manage subprocess details directly.

The main loop should remain understandable on one screen.

### 8.3 mutation.py

- Defines the `Model` protocol.
- Implements `OpenAICompatibleModel`.
- Builds the complete mutation prompt.
- Extracts full candidate source from the response.
- Handles a small, fixed number of transport retries.

Prompt construction and response parsing live together because they define the mutation boundary.

### 8.4 archive.py

- Reads and appends `records.jsonl`.
- Commits immutable candidate artifacts.
- Rebuilds the in-memory archive view.
- Computes the best successful record.
- Implements top-k selection with epsilon exploration.
- Validates lineage and artifact hashes.

There is no archive base class in v0.1.

### 8.5 runner.py

- Materializes a candidate and evaluator in a temporary directory.
- Launches a fresh evaluator subprocess.
- Applies timeout and output limits.
- Captures exit status, stdout, and stderr.
- Normalizes evaluator results.
- Converts failures into explicit record statuses.

### 8.6 cli.py

- Implements `run`, `resume`, `best`, and `inspect`.
- Loads project files and model configuration.
- Renders runtime events.
- Contains no search or evaluation algorithm.

## 9. Archive and Persistence

### 9.1 Disk layout

```text
my-experiment/
└── .nanoevolve/
    ├── run.json
    ├── records.jsonl
    └── candidates/
        ├── <record-id>/
        │   ├── source.py
        │   ├── prompt.txt
        │   ├── response.txt
        │   ├── evaluation.json
        │   ├── stdout.txt
        │   └── stderr.txt
        └── ...
```

Artifacts that do not exist for a failed attempt are omitted. The corresponding paths are null in the record.

### 9.2 Run metadata

`run.json` is an immutable initial configuration snapshot:

```json
{
  "format_version": 1,
  "task_hash": "...",
  "seed_hash": "...",
  "model": "...",
  "iterations_requested": 100,
  "random_seed": 42,
  "created_at": "..."
}
```

It does not store mutable progress. A resume command may target a generation greater than the original request without rewriting `run.json`; current progress is derived from `records.jsonl`.

### 9.3 Dynamic state

`records.jsonl` is the only dynamic state truth. Each line is one fully committed `Record`, including failed mutation attempts.

Runtime events are not persisted as an independent event-sourcing system. They can be reconstructed sufficiently from committed records for inspection and reporting.

### 9.4 Atomic commit protocol

Each mutation attempt is committed in this order:

```text
1. Create candidates/.tmp-<record-id>/.
2. Write all available prompt, response, source, evaluation, stdout, and stderr artifacts.
3. Flush artifact files.
4. Atomically rename the temporary directory to candidates/<record-id>/.
5. Append the complete Record to records.jsonl.
6. Flush and fsync records.jsonl.
7. Make the Record visible to future selection.
```

If the process terminates before the JSONL append, the candidate is not part of archive state. `resume` removes abandoned `.tmp-*` directories.

If only the final JSONL line is truncated, `resume` may discard that incomplete tail. Corruption in any earlier line is a hard error and is never silently repaired.

### 9.5 Record identity

The record ID is content-derived from stable serialized mutation metadata, including generation, parent ID, model response hash, candidate source hash when present, and run identity. The exact canonical serialization must be versioned.

Candidate artifacts store hashes in the JSONL record so `resume` and `inspect` can detect external modification.

## 10. Selection Policy

v0.1 uses one ordinary function rather than a policy class hierarchy.

The default values are:

```text
top_k = 5
epsilon = 0.2
```

Selection behaves as follows:

```text
with probability 1 - epsilon:
    rank successful records by score
    take the top-k records
    sample from them using stable rank weights

with probability epsilon:
    sample uniformly from all successful records
```

Failed records never enter the parent pool. Score ties are resolved by record ID to keep ordering stable.

The seed is evaluated and becomes the only available parent before generation 1. If seed evaluation fails, the run stops because no valid parent exists.

### 10.1 Deterministic randomness

Each generation derives its own random source from a stable cryptographic hash:

```python
generation_seed = stable_sha256_integer(run_seed, generation)
rng = random.Random(generation_seed)
```

The implementation must not use Python's process-randomized `hash()`.

Each record stores its generation seed and selection mode. Resume therefore does not depend on serialized Python RNG state.

Given the same committed archive, generation number, and run seed, parent selection is reproducible.

## 11. Evaluator Contract

The preferred evaluator form is:

```python
from nanoevolve import Evaluation


def evaluate(source_path: str) -> Evaluation:
    return Evaluation(
        score=0.91,
        feedback="Correct, but slow for large inputs.",
        metrics={"runtime_ms": 14.2},
    )
```

For convenience, the evaluator may return:

```python
Evaluation(score=0.91)
{"score": 0.91, "feedback": "...", "metrics": {...}}
0.91
```

All accepted forms are immediately normalized to `Evaluation`.

An evaluator result is invalid when:

- `score` is not a finite number.
- A metric value is not numeric or finite.
- The return structure cannot be parsed.
- `evaluate.py` does not define `evaluate()`.

## 12. Evaluator Execution

### 12.1 Process model

Each candidate is evaluated in a fresh subprocess:

```text
engine
  └── python -m nanoevolve.runner --worker
        ├── import evaluate.py
        ├── call evaluate(candidate_path)
        └── write result.json
```

The evaluator does not communicate its score through stdout. Structured results are written to a separate control file. Stdout and stderr remain ordinary captured logs.

### 12.2 Temporary directory

Each attempt uses a temporary directory containing the candidate, evaluator, and control result:

```text
/tmp/nanoevolve-<record-id>/
├── candidate.py
├── evaluate.py
└── result.json
```

The evaluator process uses this directory as its current working directory. Temporary contents are removed after completion or timeout.

v0.1 does not copy the entire user project. Evaluators that need external data must locate it explicitly, preferably through absolute paths derived from the original evaluator file.

### 12.3 Default limits

```text
evaluation timeout       30 seconds
stdout limit             64 KiB
stderr limit             64 KiB
structured result limit  1 MiB
model response limit     1 MiB
```

On POSIX systems, the runner may additionally apply best-effort CPU time, file size, subprocess count, and memory limits. Platform-specific limits must not be presented as universal guarantees.

The evaluator environment begins as a copy of the parent environment, then removes every variable whose case-insensitive name contains `API_KEY`, `ACCESS_TOKEN`, `AUTH_TOKEN`, `SECRET`, or `PASSWORD`. This filtering rule is fixed for v0.1 and must be covered by tests. Users who intentionally need credentials inside evaluation must provide them through an external sandbox or wrapper rather than the default runner.

### 12.4 Security boundary

`SubprocessRunner` provides fault isolation, not a security sandbox.

It cannot reliably prevent a candidate or evaluator from accessing the network, reading user-accessible files, invoking system programs, or interfering with other processes owned by the same user.

Documentation must tell users to run untrusted evolution inside Docker, Podman, a virtual machine, or another external sandbox. v0.1 does not advertise safe execution of hostile generated code.

## 13. Failure Semantics

Failure handling is part of the archive, not an exceptional side channel.

The status mapping is:

| Condition | Status |
| --- | --- |
| Model transport fails after retries | `model_error` |
| Response lacks one valid Python code block | `invalid_response` |
| Evaluator exits unexpectedly or raises | `evaluation_error` |
| Evaluator exceeds timeout | `evaluation_timeout` |
| Evaluator returns malformed or non-finite data | `invalid_evaluation` |
| Candidate evaluates correctly | `success` |

Every condition produces a committed record and consumes the generation. Errors are summarized in the record and preserved in detailed artifacts where available.

The run continues after ordinary mutation and evaluation failures. It stops only when:

- The seed cannot produce a valid initial parent.
- Persistent archive corruption is detected.
- Required project files disappear or change incompatibly.
- A configured target score is reached.
- A configured patience window is exhausted without a new objective-best record.
- The user interrupts the process.
- An unrecoverable internal engine invariant fails.

## 14. Observability

The engine emits runtime events through `on_event` for states such as:

```text
generation_started
parent_selected
model_completed
candidate_extracted
evaluation_completed
record_committed
new_best
generation_failed
```

The CLI is one event consumer. There is no observer registry.

Every generation must be inspectable back to:

- Parent record.
- Selection mode and generation seed.
- Exact prompt.
- Raw model response.
- Extracted source when present.
- Evaluator result.
- Stdout and stderr.
- Final status and error summary.

## 15. Dependencies and Compatibility

The runtime target is:

```text
Python >= 3.11
zero third-party runtime dependencies
```

The default implementation uses:

- `urllib.request` for non-streaming HTTP.
- `argparse` for the CLI.
- `json` for records and control messages.
- `subprocess` and `tempfile` for evaluation.
- `dataclasses` and `typing` for the public data model.

Development dependencies may be used for tests and packaging, but installing the core package must not require `requests`, Pydantic, Typer, Rich, database drivers, or provider SDKs.

## 16. Testing Strategy

### 16.1 Unit tests

Tests cover:

- Full-source response extraction.
- Ambiguous or missing code blocks.
- Evaluator return normalization.
- Non-finite scores and metrics.
- Top-k and epsilon exploration selection.
- Stable generation seed derivation.
- JSONL append and tail recovery.
- Artifact hash verification.
- Every failure-status mapping.
- Model response size limits and HTTP error handling.

### 16.2 Integration tests

Tests cover:

- Multi-generation evolution with a mock model.
- Resume after a simulated process interruption.
- Evaluator timeout.
- Evaluator exception followed by continued evolution.
- Deterministic parent selection from identical archive state.
- End-to-end behavior of all four CLI commands.
- Refusal to overwrite an existing run.
- Failure when the seed is not a valid parent.

Tests never require a live model API.

### 16.3 Examples

The repository includes:

```text
examples/
├── hello_evolve/
└── circle_packing/
```

`hello_evolve` uses a deterministic mock model and serves as the executable quick start and end-to-end test fixture.

`circle_packing` demonstrates a real optimization task and is run manually with a configured model endpoint.

## 17. Acceptance Criteria

v0.1 is complete only when all of the following are true:

1. A new user can run the deterministic example within five minutes.
2. The main evolution loop in `engine.py` can be understood on one screen.
3. An interrupted run preserves every fully committed candidate.
4. Every generation can be traced to its parent, prompt, response, source, and evaluation artifacts.
5. Selection is reproducible from the same archive, generation, and random seed.
6. Evaluator failures do not corrupt state or prevent later generations from running.
7. The installed package has no third-party runtime dependencies.
8. The core package stays near or below 1,200 lines without sacrificing readability.
9. The repository includes tests, a README, and both examples.
10. Documentation states the subprocess security boundary accurately.

The line budget is a complexity budget, not an invitation to compress readable code or combine unrelated responsibilities.

## 18. Version Roadmap

### v0.1: Nano core

- Full-source mutation.
- Sequential evolution.
- JSONL archive.
- Top-k plus exploration.
- Subprocess evaluator.
- Four CLI commands.

### v0.2: Stronger mutation context

- SEARCH/REPLACE diff mutation.
- EVOLVE-BLOCK markers.
- Inspiration candidates.
- Artifact feedback.

### v0.3: Mini workspace

- Multi-file workspaces.
- External sandbox command integration.
- Parallel evaluator workers.
- Optional SQLite archive.
- Multiple selection metrics.

### v0.4: Quality diversity

- Simplified MAP-Elites.
- User-provided feature coordinates.
- Optional islands and migration.

### v0.5: Target-aware stopping

- Persisted target score.
- Seed and resume pre-checks.
- Explicit target events.
- Deterministic parallel batch boundaries.

### v0.6: Stagnation-aware stopping

- Persisted patience window.
- Failed generations count as non-improving attempts.
- Resume-time stagnation pre-checks.
- Deterministic parallel batch-boundary decisions.

Each stage must respond to observed limitations in real use. Features are not added solely to claim parity with OpenEvolve.

## 19. Key Architectural Decisions

The approved decisions are:

1. Use six internal semantic modules while exposing one primary function and four CLI commands.
2. Treat the LLM only as a mutation operator.
3. Use full-source output in v0.1 and defer patch mutation.
4. Use `run.json`, `records.jsonl`, and immutable candidate directories instead of SQLite or full event sourcing.
5. Keep prompt construction and response parsing in the mutation boundary.
6. Use ordinary selection functions rather than a policy class hierarchy.
7. Count every mutation attempt as one generation, including failures.
8. Treat subprocess execution as fault isolation, not a security sandbox.
9. Use stable per-generation random seeds instead of persisted RNG state.
10. Keep metrics observational until a later multi-objective version.

These decisions define the v0.1 scope and should not be revisited during implementation unless a concrete contradiction is discovered.
