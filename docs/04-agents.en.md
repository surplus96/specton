# Agents

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](04-agents.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](04-agents.en.md)

> Status: **Skeleton (before the meeting)** · to be written after meeting decisions.
> Purpose: define each agent's inputs, outputs, and validation, plus reviewer perspective settings.
> Source: parent planning folder `docs/개발착수_문서/04_에이전트_상세설계.md`

## Common rules

- [ ] Node structure: input selection → prompt → LLM client → output validation → reference check → ID assignment
- [ ] Up to 2 retries, model assignment (ADR-0007)

## Design agents A01–A04

- [ ] A01 Requirement analysis
- [ ] A02 Function design
- [ ] A03 Entities·attributes·CRUD
- [ ] A04 Relationship design

## Review perspectives A05–A08

- [ ] Config file format (prompt, checklist, input selection, false-positive criteria)
- [ ] Owner per perspective

## A09 router

- [ ] Invocation conditions
- [ ] Allowed return stages

## Rule checks RULE-01–07

- [ ] Blocking criteria and exemptions per rule
