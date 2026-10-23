# Contributing

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](CONTRIBUTING.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](CONTRIBUTING.en.md)

Work is tracked in **GitHub Issues + Projects**, and code is merged with **GitHub Flow** (a protected `main` plus short-lived work branches).

## Workflow

1. Create or get assigned an issue (templates: Task / Bug). Add a milestone M1–M5 and `role:`·`agent:` labels.
2. Branch from the latest `main`.
   ```bash
   git switch main && git pull
   git switch -c feat/12-a01-requirement-node
   ```
3. Commit in small steps and bring in `main` every morning (`git fetch && git rebase origin/main`).
4. Open a PR with `Closes #issue` in the body. Merge with **Squash** only.
5. Merge branches **within 2 days**. If it takes longer, split the issue.

## Naming

| Target | Format | Example |
|---|---|---|
| Branch | `<type>/<issue>-<summary>` | `feat/12-a01-requirement-node` |
| Commit · PR title | `<type>: <description> (#issue)` | `feat: add A01 fixture tests (#12)` |

`type`: feat, fix, refactor, docs, test, chore, ci, perf

## Review

- Merge after **1 approval** from someone other than the author. `.github/CODEOWNERS` assigns reviewers by path.
- Changes to `specton/contracts/` get the `contract-change` label and need **2 approvals**.
- Never report a test you did not run as passing.

## Before merging

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run python -m specton.packs.build --check
cd frontend && npm run lint && npm run build   # if you changed frontend
```

## Conflict-prone files

| File | Rule |
|---|---|
| `uv.lock`, `frontend/package-lock.json` | Add dependencies in a dedicated PR. Never resolve conflicts by hand; regenerate with `uv lock` / `npm install` |
| `specton/contracts/` | Announce changes in an issue first. Small, frequent PRs |
| `specton/graph.py` | Only the integration owner (R1) edits it. Request node wiring through an issue |
| Generated files in `domain_packs/` (marked `GENERATED`) | Do not edit directly. Fix the inputs and include the `uv run python -m specton.packs.build` output in the same PR ([guide](domain_packs/README.en.md)) |

## Labels

| Label | Purpose |
|---|---|
| `type:task`, `type:bug` | Issue type (added by templates) |
| `role:R1` – `role:R5` | Owning role |
| `agent:A01` – `agent:A09` | Related agent |
| `contract-change` | Data contract change (2 approvals) |
| `blocked` | Waiting on another issue or decision |
| `db`, `llm` | Targets for the matching CI jobs |

## Security

- Never commit `.env`, API keys, original customer documents, or run outputs.
- Run real LLM call tests (`-m llm`) manually, only after budget approval.
