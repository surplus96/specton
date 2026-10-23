# Testing · evaluation

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](07-testing-eval.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](07-testing-eval.en.md)

> Status: **Skeleton (before the meeting)** · to be written after meeting decisions.
> Purpose: define test layers and the AI evaluation method.
> Source: parent planning folder `docs/개발착수_문서/09_테스트_평가계획.md`, `관리표/테스트_케이스.csv`

## Test layers

- [ ] unit (`pytest`)
- [ ] db (`pytest -m db`)
- [ ] llm (`pytest -m llm`, after budget approval)
- [ ] e2e

## Evaluation data

- [ ] Inventory and maintenance case counts (ADR-0014)
- [ ] Answer key creation and approval process, owners
- [ ] `eval/` structure, origin: synthetic marking

## Metrics

- [ ] Classification F1
- [ ] Function·entity·relationship matching
- [ ] Defect detection rate, false positives
- [ ] DDL execution success rate
- [ ] Time·tokens

## Report format

- [ ] Run ID, versions, results, limitations
