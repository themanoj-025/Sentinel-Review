# Contributing to Sentinel Review

Thank you for considering contributing to Sentinel Review! 🛡️

We welcome contributions of all types — bug reports, feature requests, documentation improvements, and code changes.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Coding Conventions](#coding-conventions)
- [Testing](#testing)
- [Documentation](#documentation)
- [Questions?](#questions)

## Code of Conduct

This project adheres to the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/your-username/sentinel-review.git
   cd sentinel-review
   ```
3. **Set up** the development environment:
   ```bash
   make install        # Install Python dependencies
   cp .env.example .env  # Configure environment variables
   ```
4. **Create a branch** for your work:
   ```bash
   git checkout -b feat/your-feature-name
   ```

## Development Workflow

```bash
# Run lint + tests (what CI does)
make check

# Or individually:
make lint          # ruff check
make test          # pytest with coverage
make format        # ruff format

# Docker-based development:
make docker-up     # Start all services
make docker-down   # Stop all services
```

## Pull Request Guidelines

1. **Keep PRs focused** — a single concern per PR. Split large changes into smaller PRs.
2. **Write meaningful commit messages** following [conventional commits](https://www.conventionalcommits.org/):
   - `feat:` — new feature
   - `fix:` — bug fix
   - `test:` — adding or updating tests
   - `docs:` — documentation changes
   - `chore:` — maintenance tasks
3. **Update documentation** if you change behavior (README, docs/*, docstrings).
4. **Ensure CI passes** — all tests must pass and lint must be clean.
5. **Include tests** for new functionality. We have ~240 tests and aim to keep coverage ≥80%.

## Coding Conventions

- **Python 3.12+** — use modern Python features
- **Type hints** — all functions must have type annotations
- **Docstrings** — all modules and public functions need docstrings
- **Imports** — organized with `ruff` (automatic via `make lint-fix`)
- **Line length** — max 100 characters
- **Formatting** — use `ruff format` (matching `make format`)
- **Use `from __future__ import annotations`** in all new files

## Testing

```bash
# Run all tests
cd backend && pytest

# Run with coverage
cd backend && pytest --cov=. --cov-report=term-missing

# Run a specific test file
cd backend && pytest tests/test_signature.py -v

# Run without migrations (faster for local dev)
cd backend && pytest --nomigrations
```

We use:
- **pytest** + **pytest-django** for the test runner
- **respx** for mocking HTTP calls (GitHub API)
- **unittest.mock** for internal mocking (LLM, Semgrep)
- **pytest-cov** for coverage reporting

## Documentation

Key documentation lives in the `docs/` directory:

| File | Purpose |
| ------ | --------- |
| `architecture.md` | System architecture and data flow |
| `../decisions/decisions.md` | Architectural Decision Records (21 ADRs) |
| `../technical/security-notes.md` | Threat model and security controls |
| `../reference/evaluation-report.md` | Test results, evaluation metrics, multi-model comparison |

If your change affects architecture, configuration, or security, please update the relevant docs.

## Questions?

Open a [GitHub Discussion](https://github.com/sentinel-review/sentinel-review/discussions) or check the existing [Issues](https://github.com/sentinel-review/sentinel-review/issues).
