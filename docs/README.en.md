# Development docs

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](README.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](README.en.md)

Only documents needed to build Specton live here. Original planning and meeting materials are in the parent planning folder `docs/`.

| Document | Contents | Status |
|---|---|---|
| [01 Overview · scope](01-overview.en.md) | Goals, MVP scope, exclusions | Skeleton |
| [02 Requirements](02-requirements.en.md) | REQ list, acceptance criteria, scope | Skeleton |
| [03 Architecture](03-architecture.en.md) | Components, execution flow, state | Skeleton |
| [04 Agents](04-agents.en.md) | A01–A09 inputs/outputs, reviewer settings | Skeleton |
| [05 Data contracts](05-data-contracts.en.md) | Pydantic models, IDs, versions | Skeleton |
| [06 API](06-api.en.md) | Endpoints, SSE, errors | Skeleton |
| [07 Testing · evaluation](07-testing-eval.en.md) | Test layers, metrics, answer key management | Skeleton |
| [08 Roles · collaboration](08-roles.en.md) | Owners, backups, code ownership | Skeleton |
| [adr/](adr/README.en.md) | Decision records | Skeleton |

Install and run commands are in the repository [README](../README.en.md).

## Writing rules

- Write down decided items only. Mark open items as `TBD (ADR-xxxx)`.
- When a contract or API changes, update the docs in the same PR as the code.
- Never include original customer documents or API keys.
