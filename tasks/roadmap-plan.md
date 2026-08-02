# Implementation Plan: NanoEvolve v0.2-v0.4 Roadmap

## Overview

Implement every published roadmap item while preserving NanoEvolve's defining constraints: one public `evolve()` entry point, four CLI commands, six semantic modules, file-visible state, deterministic resume, and zero third-party runtime dependencies. New behavior is opt-in; existing v0.1 projects and archives remain valid.

## Architecture Decisions

- Keep candidates as immutable workspace snapshots. A single-file seed remains a one-file workspace named after the seed file.
- Support three mutation modes: `full`, `search_replace`, and `evolve_blocks`. Full mode remains the default.
- Represent multi-file model output as explicit file sections; reject path traversal, duplicate paths, and ambiguous patches.
- Add inspiration and artifact feedback only as explicit prompt sections derived from committed records.
- Keep generation order deterministic. Model calls remain sequential; evaluator work may run concurrently inside deterministic batches and commits remain generation ordered.
- Support `jsonl` and `sqlite` record indexes behind the same file artifact layout. JSONL remains the default.
- Define multi-objective ranking as deterministic lexicographic ordering over named score/metric objectives with explicit maximize/minimize direction.
- Define MAP-Elites cells from evaluator metric names and numeric bin widths. Missing feature metrics make a record ineligible for a cell, not unsuccessful.
- Assign each generation to an island deterministically. Parent selection is local by default; migration periodically widens the eligible pool.
- Store every semantic option in immutable run metadata and reject incompatible resume attempts.

## Public Options

`evolve()` gains keyword-only options with conservative defaults:

- `mutation_mode="full"`
- `evolve_blocks=False` as the CLI-friendly alias for block mode
- `inspiration_count=0`
- `artifact_feedback=()`
- `sandbox_command=None`
- `workers=1`
- `archive_backend="jsonl"`
- `objectives=("score:max",)`
- `features=()` and `feature_bins={}`
- `islands=1` and `migration_interval=0`

CLI `run` and `resume` expose corresponding flags while `best` and `inspect` remain unchanged.

## Dependency Graph

```text
workspace snapshots + record metadata
        |
        +--> mutation formats + prompt context
        |
        +--> runner sandbox + parallel batches
        |
        +--> JSONL/SQLite persistence
                    |
                    +--> multi-objective ranking
                              |
                              +--> MAP-Elites features
                                        |
                                        +--> islands/migration
```

## Task List

### Phase 1: Mutation Context

#### Task 1: Workspace snapshot primitives

**Acceptance criteria:**
- Single files and directories normalize to safe relative-path mappings.
- Candidate artifacts preserve nested workspace paths immutably.
- Existing one-file archives reopen unchanged.

**Verification:** `python -m unittest tests.test_workspace -v`

#### Task 2: SEARCH/REPLACE mutations

**Acceptance criteria:**
- Exact file-scoped replacements apply deterministically.
- Missing, repeated, overlapping, or unsafe replacements are rejected.
- Full-source responses remain the default behavior.

**Verification:** `python -m unittest tests.test_mutation -v`

#### Task 3: EVOLVE-BLOCK mutations

**Acceptance criteria:**
- Only text inside paired `EVOLVE-BLOCK` markers may change.
- Marker names are unique and preserved.
- Changes outside declared blocks are rejected.

**Verification:** `python -m unittest tests.test_mutation -v`

#### Task 4: Inspiration and artifact feedback

**Acceptance criteria:**
- Prompts may include a deterministic set of successful inspiration records.
- Named committed artifacts may be included with explicit size bounds.
- Prompt content remains fully persisted and inspectable.

**Verification:** `python -m unittest tests.test_engine -v`

### Checkpoint: v0.2

- Mutation modes work for one-file and multi-file candidates.
- Existing v0.1 tests remain green.

### Phase 2: Mini Workspace

#### Task 5: Multi-file evolution

**Acceptance criteria:**
- Directory seeds evaluate as workspace directories.
- Multi-file mutations may add, edit, and delete safe relative paths.
- Record artifacts reconstruct every successful workspace snapshot.

**Verification:** `python -m unittest tests.test_workspace tests.test_engine -v`

#### Task 6: External sandbox command

**Acceptance criteria:**
- Evaluator worker commands may be wrapped by an explicit external command prefix.
- Timeout, output capture, and status mapping remain unchanged.
- Run metadata records the configured wrapper without secrets.

**Verification:** `python -m unittest tests.test_runner -v`

#### Task 7: Parallel evaluator workers

**Acceptance criteria:**
- `workers > 1` evaluates deterministic generation batches concurrently.
- Records commit in generation order regardless of completion order.
- Resume never repeats a committed generation.

**Verification:** `python -m unittest tests.test_engine -v`

#### Task 8: Optional SQLite archive

**Acceptance criteria:**
- SQLite stores the same serialized records and preserves immutable artifacts.
- Reopen, best, inspect, resume, and integrity checks match JSONL behavior.
- Backend choice is immutable for a run.

**Verification:** `python -m unittest tests.test_archive -v`

#### Task 9: Multiple selection metrics

**Acceptance criteria:**
- Named score/metric objectives support maximize and minimize directions.
- Best and top-k selection use deterministic lexicographic ranking.
- Missing objective metrics exclude a record from selection with a clear error if none remain.

**Verification:** `python -m unittest tests.test_archive -v`

### Checkpoint: v0.3

- Both archive backends pass the same behavioral contract.
- Workspace, sandbox, parallelism, and multi-objective runs resume deterministically.

### Phase 3: Quality Diversity

#### Task 10: Feature coordinates and MAP-Elites

**Acceptance criteria:**
- Feature coordinates derive from named evaluator metrics.
- Numeric bin widths map records to deterministic cells.
- MAP-Elites keeps the best ranked record per occupied cell and samples elites deterministically.

**Verification:** `python -m unittest tests.test_archive -v`

#### Task 11: Islands and migration

**Acceptance criteria:**
- Records carry deterministic island identifiers.
- Normal selection uses the target island's pool.
- Migration generations may select from all islands and record that selection mode.

**Verification:** `python -m unittest tests.test_archive tests.test_engine -v`

#### Task 12: CLI, docs, and release acceptance

**Acceptance criteria:**
- `run` and `resume` expose every roadmap option without adding commands.
- English and Chinese roadmap/checklists describe implemented behavior and boundaries.
- Tests, compile, package build, clean-wheel demo, and release checker pass.

**Verification:** `python scripts/release_check.py`

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Feature combination expands control flow | High | Normalize options once and keep selection/mutation helpers pure. |
| Parallel evaluation weakens determinism | High | Freeze parents/prompts first and commit completed results by generation. |
| Workspace paths enable traversal | High | Accept only normalized relative POSIX paths without `..` or absolute roots. |
| SQLite and JSONL drift | High | Store identical record JSON and run a shared backend contract test. |
| Quality-diversity semantics become framework-like | Medium | Use named metrics, fixed bins, deterministic cells, and no policy hierarchy. |
| Resume silently changes algorithms | High | Persist normalized options and compare them on every resume. |

## Open Questions

None. The roadmap is implemented using the smallest deterministic semantics consistent with the published promises.
