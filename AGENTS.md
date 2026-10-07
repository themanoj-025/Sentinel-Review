# AGENTS.md — sentinel-review

> Canonical project instructions. Pointers like `CLAUDE.md` or
> `.github/copilot-instructions.md` should say "See AGENTS.md".

---

## Project overview

**sentinel-review** — a code-review and security-sentinel pipeline.
Core components:

- **API** — review request / result service.
- **Review** — static-analysis + model-based review pipeline.
- **Web** — dashboard for reviewing findings.

Stack: Python 3.11+ · FastAPI · Ruff · Bandit · Streamlit.

---

## Exact commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Lint / typecheck / test
make lint
pre-commit run --all-files
python -m mypy . --ignore-missing-imports
python -m pytest tests/ -v --cov=. --cov-fail-under=70

# Run
uvicorn api.main:app --reload
streamlit run dashboard/app.py
```

---

## Folder map

| Path | Purpose |
|------|---------|
| `api/` | FastAPI application (routes, services) |
| `review/` | Review pipeline + models |
| `dashboard/` | Streamlit review dashboard |
| `tests/` | pytest suite |
| `.github/workflows/` | CI (ruff, mypy, pytest, gitleaks, trivy) |

## Do / don't

- **Do** keep the review interface stable so the static + model analysis
  can be extended independently.
- **Do not** commit `.env` files.
- **Do not** commit internal findings with real secrets.

## Security rules

- No secrets in the repository; `gitleaks` CI gate gates on hits.
- Review findings with real tokens must be stripped before any file
  leaves the sandbox.

## AI-assistance convention

Commits authored by AI must carry the trailer:

```text
AI-Assisted: yes | no | partial
```

See `.gitmessage` for the template. Do not rewrite historic commits
retroactively.
