# Contributing to NanoEvolve

Thank you for helping keep NanoEvolve small, transparent, and reliable.

## Development Setup

NanoEvolve supports Python 3.11 and newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The runtime package intentionally has no third-party dependencies.

## Validation Commands

Run focused tests while developing, then run the complete release surface:

```bash
python -m unittest discover -s tests -v
python -m compileall nanoevolve examples
python scripts/release_check.py
python examples/hello_evolve/demo.py
python -m nanoevolve --version
```

## Development Method

Behavior changes use test-driven development:

1. Add one focused test describing the desired behavior.
2. Run it and confirm it fails for the intended reason.
3. Add the smallest implementation that makes it pass.
4. Run the focused test and the complete suite.
5. Refactor only while tests remain green.

Do not add production behavior first and tests afterward.

## Architecture Boundary

The core uses six semantic modules:

| Module | Responsibility |
| --- | --- |
| `types.py` | Public immutable records and events |
| `mutation.py` | Prompt, model request, and source extraction |
| `archive.py` | JSONL state, artifacts, integrity, and selection |
| `runner.py` | Evaluator subprocess and result normalization |
| `engine.py` | Sequential evolution control flow |
| `cli.py` | `run`, `resume`, `best`, and `inspect` commands |

New changes should preserve these principles:

- Ordinary functions before class hierarchies.
- Explicit files before hidden state.
- One dynamic state truth: `records.jsonl`.
- No runtime dependency without a reviewed design need.
- No provider, policy, plugin, or observer registry for a single implementation.
- No claim that evaluator subprocesses are a security sandbox.

Larger algorithmic changes should begin with a design document under `docs/superpowers/specs/`.

## Tests

Tests use the Python standard-library `unittest` framework. Live model credentials are never required. HTTP behavior uses a local test server, and evaluator behavior uses real subprocesses.

When fixing a defect, add a regression test that reproduces it before changing production code.

## Documentation

User-facing changes must update both:

- `README.md`
- `README.zh-CN.md`

Keep their major section structure aligned. Internal IDs, temporary paths, credentials, and unsupported claims do not belong in release-facing prose.

## Pull Request Checklist

- [ ] The change has a focused purpose.
- [ ] New behavior has a test that failed before implementation.
- [ ] The complete unittest suite passes.
- [ ] `compileall` passes for package and examples.
- [ ] `scripts/release_check.py` passes.
- [ ] Runtime dependencies remain unchanged or have explicit design approval.
- [ ] English and Chinese README content is synchronized when user behavior changes.
- [ ] Security and sandbox boundaries remain accurate.
- [ ] No author, license, repository URL, or release destination is guessed.

## Release Ownership

Repository creation, licensing, package publication, and maintainer identity are owner decisions. Contributions should not fill these fields with placeholders or assumptions.
