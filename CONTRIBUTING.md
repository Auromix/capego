# Contributing to CapEgo

Thanks for helping make ego data easier to collect, inspect and use. English and Chinese issues and pull requests are welcome.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,data,export]'
ruff check src tests scripts
ruff format --check src tests scripts
pytest -q
python scripts/demo_pipeline.py --root runtime/contribution-check --egowam
```

Use a fresh runtime directory for integration runs. The automated tests use small generated fixtures; public-data runs are documented separately in [real-data.md](docs/real-data.md). No GPU or downloaded dataset is required for unit tests. Optional model/training dependencies should not become base dependencies.

## Making a change

1. For product behavior or public-contract changes, explain the concrete use case in an issue and update the relevant `design/` document.
2. Keep changes focused. Add source adapters under `importers/`, processing algorithms under `backends/`, and target writers under `exporters/`; see [architecture](docs/architecture.md).
3. Preserve compatibility where practical and record migration requirements for schema changes. Never turn missing or estimated data into measured ground truth.
4. Run checks relevant to the change. Add regression tests for meaningful failures, not tests that merely repeat implementation details.
5. Describe the problem, resulting behavior, validation and limitations in the PR. Keep README language versions aligned.

Do not commit recordings, generated datasets, model weights, credentials, personal information or runtime databases. Include small original fixtures or download instructions with source/license details instead. Reports must distinguish software checks, hardware measurements, model quality and human acceptance.

Contributions are made under the repository's Apache-2.0 license. Only contribute material you have the right to license. See [third-party notices](THIRD_PARTY.md) and [community conduct](CODE_OF_CONDUCT.md).
