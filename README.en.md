# Specton

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](README.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](README.en.md)

A LangGraph-based agent service that reads customer requirement documents, drafts a **functional specification, ERD, DDL, and RTM**, and reviews them for omissions and contradictions.
Team Seolgyero (설계로) · Hanwha Systems K-New Deal Academy, Capstone Project 8.

The design reference documents (Korean) live in [docs/](docs/README.md), and decision records in [docs/adr/](docs/adr/README.md).

## Tech stack

| Area | Tools |
|---|---|
| Language · packaging | Python 3.12, uv |
| LLM · workflow | OpenAI API, LangGraph |
| Contracts · validation | Pydantic, pglast |
| API | FastAPI |
| DB | PostgreSQL 18 (Docker) |
| Web | React (`frontend/`) |
| Quality | ruff, mypy, pytest |

Undecided: PDF·HWPX engines (ADR-0004), UI library (ADR-0005), AWS setup (ADR-0013).

## Getting started

```bash
cp .env.example .env              # enter keys only in your local environment
uv sync                           # install dependencies (.venv)
docker compose up -d db           # PostgreSQL 18 (app + sandbox)
uv run uvicorn specton.api.main:app --reload
curl localhost:8000/health
```

Web (`frontend/`):

```bash
cd frontend && npm install && npm run dev
```

## Quality checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                     # unit tests (excludes db·llm)
uv run pytest -m db               # requires the isolated DB
uv run pytest -m llm              # real LLM calls; run manually after budget approval
```

## Domain packs

`domain_packs/` holds inputs based on the 8th edition of the Korean Public Data Common Standard. Human-written files and generated files are kept separate ([guide](domain_packs/README.md), Korean).

```bash
uv run python -m specton.packs.build          # regenerate after editing inputs
uv run python -m specton.packs.build --check  # check generated files are up to date (CI)
```

## Folder structure

```text
specton/
  contracts/    data contracts between stages (state, LLM I/O, Finding)
  ingest/       Excel·CSV·PDF·HWPX extraction, keeps source locations
  packs/        domain pack loader
  llm/          shared LLM client, retries, prompt versions
  nodes/        agent nodes A01–A09
  codegen/      IDs, naming, N:M, FKs; Mermaid·DDL·RTM generation
  review/       rule checks, configurable reviewer, evidence merging
  validate/     DDL parsing, isolated DB execution checks
  persistence/  platform storage, checkpointer
  export/       intermediate Markdown; final PDF·SQL·Excel/CSV
  api/          FastAPI
  config.py     settings
domain_packs/   common · inventory (stock·materials) · maintenance (equipment)
eval/           evaluation data and answer keys (marked origin: synthetic)
frontend/       React web
tests/          unit · integration · e2e
```

## Collaboration

See [CONTRIBUTING.md](CONTRIBUTING.md) (Korean) for details.

- Work is tracked in GitHub Issues and the [Projects board](https://github.com/users/surplus96/projects/1). Branch `feat/<issue>-summary`, PR title `feat: description`.
- A PR states `Closes #issue` and its test results and needs one approval from someone other than the author. Only R1 (@surplus96) merges into `main`, using squash. Contract (`contracts/`) changes need two approvals.
- Nodes stay thin adapters; generators and validators never import the LLM client. Domain constants are read from packs.
- Never commit customer documents, API keys, or run outputs.

## License

[MIT](LICENSE). The Public Data Common Standard CSVs in `domain_packs/sources/` are public data from the Ministry of the Interior and Safety (no usage restrictions); their sources are recorded in `domain_packs/sources/sources.yaml`.
