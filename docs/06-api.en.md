# API

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](06-api.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](06-api.en.md)

> Status: **Skeleton (before the meeting)** · to be written after meeting decisions.
> Purpose: endpoints and error rules for the run control API.
> Source: parent planning folder `docs/개발착수_문서/06_API_명세서.md`, `관리표/openapi.json`

## Endpoints

- [ ] POST /runs
- [ ] GET /runs, /runs/{id}, /runs/{id}/view
- [ ] GET /runs/{id}/events (SSE)
- [ ] POST /runs/{id}/resume, /cancel
- [ ] GET /runs/{id}/artifacts/{kind}

## Output formats

- [ ] Allowed formats per kind (intermediate md, final pdf)

## Errors · authentication

- [ ] Error format code/message/run_id/retryable
- [ ] Sessions and access scope (ADR-0011)

## OpenAPI

- [ ] Where `openapi.json` is stored and how it is updated
