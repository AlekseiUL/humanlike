# Acknowledgements and third-party tooling

Humanlike Agent Kit's runtime code and bundled foundation pack are released under the repository's MIT License. The installed Python package declares no third-party runtime dependencies.

The following external open-source projects are used for development, packaging, continuous integration, or as an integration target. They are not relicensed by this repository, and their original licenses continue to apply.

| Project | Role | License | Source |
| --- | --- | --- | --- |
| Python | Runtime platform | PSF License | https://www.python.org/ |
| setuptools | PEP 517 build backend | MIT | https://github.com/pypa/setuptools |
| build | Python package builder used in tests | MIT | https://github.com/pypa/build |
| pytest | Test runner | MIT | https://github.com/pytest-dev/pytest |
| pytest-cov | Coverage integration | MIT | https://github.com/pytest-dev/pytest-cov |
| Ruff | Linter | MIT | https://github.com/astral-sh/ruff |
| uv | Locked development environment and CI package tooling | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| actions/checkout | GitHub Actions checkout step | MIT | https://github.com/actions/checkout |
| actions/setup-python | GitHub Actions Python setup step | MIT | https://github.com/actions/setup-python |
| astral-sh/setup-uv | GitHub Actions uv setup step | MIT | https://github.com/astral-sh/setup-uv |
| Hermes Agent | Reference integration target; no Hermes source code is bundled | MIT | https://github.com/NousResearch/hermes-agent |
| Keep a Changelog | Changelog format reference | CC BY 4.0 | https://keepachangelog.com/en/1.1.0/ |

## Provenance statement

- This GitHub repository is not a fork.
- The runtime has no third-party Python runtime dependencies.
- No third-party source file is knowingly copied into the package.
- The Hermes adapter is an independent compatibility layer targeting documented hook names; Hermes Agent code is not redistributed here.
- The bundled foundation records are project-original content and are redistributed under MIT together with the package.

If you identify omitted attribution or a licensing concern, follow [SECURITY.md](SECURITY.md) for private disclosure when the issue is sensitive, or open a regular GitHub issue for non-sensitive documentation corrections.
