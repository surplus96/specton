# Architecture

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](03-architecture.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](03-architecture.en.md)

> Status: **Skeleton (before the meeting)** · to be written after meeting decisions.
> Purpose: define components, execution flow, and state transitions.
> Source: parent planning folder `docs/개발착수_문서/03_시스템_아키텍처.md`, `LLM_기능_설계.md`

## Component diagram

- [ ] Web (React) → API (FastAPI) → runner (LangGraph) → LLM·DB·file storage
- [ ] Deployment layout (ADR-0013)

## Execution flow

- [ ] Input → A01 → HITL 1 → A02–A04 → model consolidation → generation (parallel) → review → routing → HITL 2 → export
- [ ] How reviewers run (ADR-0008)

## State · versions

- [ ] Run state transitions
- [ ] revision·iteration·rework limits
- [ ] Runner and resume approach (ADR-0012)

## Code boundaries

- [ ] LLM judgment vs. code generation responsibilities
- [ ] Responsibilities per folder (under `specton/`)
