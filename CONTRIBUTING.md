# Contributing

Contributions are welcome when they keep Humanlike Agent Kit deterministic, provider-neutral, bounded, and testable offline.

## Before opening a pull request

1. Create a focused branch from `main`.
2. Keep runtime behavior independent of network calls and model providers.
3. Add or update tests for every behavior change, including a failure case.
4. Update documentation when a command, schema, hook, path, or trust boundary changes.
5. Run the full local gate:

```bash
uv sync --locked --all-extras
uv run pytest -q
uv run ruff check .
uv run python scripts/privacy_gate.py .
SOURCE_DATE_EPOCH=1767225600 uv build --no-build-isolation
```

## Pull request scope

A useful pull request explains:

- the observable problem;
- the root cause;
- the smallest coherent change;
- verification performed;
- compatibility or privacy impact;
- rollback when the change alters state or packaging.

Do not include secrets, private transcripts, production memory databases, personal data, local absolute paths, or generated build artifacts.

## Behavioral and security changes

Changes to routing, persona loading, memory, privacy controls, foundation records, or the Hermes adapter need regression tests and a short threat-boundary note. Passing the bundled conformance suite proves only its declared checks; it is not evidence of general model quality or safety.

For vulnerabilities, do not open a public issue. Follow [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contribution is licensed under the repository's [MIT License](LICENSE).
