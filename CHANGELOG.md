# Changelog

All notable changes to NanoEvolve are documented in this file.

The format follows the structure of Keep a Changelog. Version publication remains an owner-controlled action; this file records the validated project milestones present in the workspace.

## [Unreleased]

### Added

- Module execution through `python -m nanoevolve`.
- CLI and module `--version` support.
- Typed-package marker and explicit wheel/source-distribution contents.
- Cross-platform CI design for Python 3.11 through 3.13.
- Contributor guide, security policy, and release-check tooling.

### Changed

- Expanded English and Chinese README release guidance.
- Hardened package metadata without inventing author, license, or repository fields.

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
