# Changelog

All notable changes to NanoEvolve are documented in this file.

The format follows the structure of Keep a Changelog. Version publication remains an owner-controlled action; this file records the validated project milestones present in the workspace.

## [0.6.0] - 2026-08-02

### Added

- Persisted `patience` / `--patience` stopping after consecutive non-improving generations, including failed attempts.
- Resume-time stagnation pre-checks and deterministic parallel batch-boundary decisions.
- Explicit `patience_exhausted` events in human-readable and JSON Lines streams.

### Changed

- Raised the explicit core complexity budget from 1,900 to 1,950 lines for stagnation-aware stopping.

## [0.5.0] - 2026-08-02

### Added

- Persisted `target_score` / `--target-score` stopping for seed evaluation, resumed runs, sequential generations, and deterministic parallel batches.
- Explicit `target_reached` events in both human-readable and JSON Lines event streams.
- Clean-wheel execution of the complete CLI integration suite.

## [0.4.4] - 2026-08-02

### Added

- Direct, exact artifact output through `inspect --artifact NAME`, while preserving the four-command CLI boundary.
- Clean-wheel verification that persisted prompt artifacts can be exported without framing text.

## [0.4.3] - 2026-08-02

### Added

- Machine-readable JSON Lines event streams for `run` and `resume` through `--json-events`, without adding another CLI command.
- Source-checkout and clean-wheel help verification for the structured event option.

## [0.4.2] - 2026-08-02

### Added

- Reproducible, no-network eight-point circle-packing benchmark with an inspectable score trajectory from `0.4000000000` to `0.5176380902`.
- Cross-platform and clean-wheel CI coverage for the benchmark path.

## [0.4.1] - 2026-08-02

### Added

- Deterministic `roadmap_showcase` combining multi-file workspaces, SEARCH/REPLACE, inspiration context, artifact feedback, parallel evaluators, SQLite, multi-objective selection, MAP-Elites, islands, and migration.
- Cross-platform and clean-wheel CI smoke coverage for the combined advanced path.

## [0.4.0] - 2026-08-02

### Added

- Module execution through `python -m nanoevolve`.
- CLI and module `--version` support.
- Typed-package marker and explicit wheel/source-distribution contents.
- Cross-platform CI design for Python 3.11 through 3.13.
- Contributor guide, security policy, and release-check tooling.
- SEARCH/REPLACE and EVOLVE-BLOCK mutation formats.
- Inspiration candidates and bounded artifact feedback in persisted prompts.
- Multi-file workspace snapshots and evaluator support.
- External sandbox command wrappers and deterministic parallel evaluator batches.
- Optional SQLite record indexing.
- Lexicographic multi-objective selection.
- Metric-binned MAP-Elites, feature coordinates, islands, and migration.

### Changed

- Expanded English and Chinese README release guidance.
- Hardened package metadata without inventing author, license, or repository fields.
- Raised the explicit core complexity budget from the v0.1 threshold to 1,900 lines for the completed roadmap.

## [0.1.0] - 2026-08-02

### Added

- Minimal `select → mutate → evaluate → archive` evolution loop.
- OpenAI-compatible, non-streaming model client with no hidden system message.
- Full-source mutation response format.
- Append-only JSONL archive with immutable, hashed candidate artifacts.
- Deterministic top-k selection with epsilon exploration.
- Fresh-process evaluator execution with timeout and explicit failure states.
- `run`, `resume`, `best`, and `inspect` CLI commands.
- Deterministic no-network demo and circle-packing example.
- English and Simplified Chinese project documentation.

### Security

- Filtered common API-key, token, secret, and password environment variables from evaluator subprocesses.
- Documented that subprocess execution is fault isolation rather than a hostile-code sandbox.
