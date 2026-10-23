# 테스트·평가

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-1f6feb)](07-testing-eval.md) [![English](https://img.shields.io/badge/lang-English-lightgrey)](07-testing-eval.en.md)

> 상태: **골격 (회의 전)** · 회의 결정 반영 후 작성한다.
> 목적: 테스트 층위와 AI 평가 방법을 정의한다.
> 원본: 상위 기획 폴더 `docs/개발착수_문서/09_테스트_평가계획.md`, `관리표/테스트_케이스.csv`

## 테스트 층위

- [ ] unit (`pytest`)
- [ ] db (`pytest -m db`)
- [ ] llm (`pytest -m llm`, 예산 승인 후)
- [ ] e2e

## 평가 데이터

- [ ] 재고·설비 건수 (ADR-0014)
- [ ] 정답 제작·승인 절차와 담당
- [ ] `eval/` 구조, origin: synthetic 표시

## 지표

- [ ] 분류 F1
- [ ] 기능·엔티티·관계 매칭
- [ ] 결함 탐지율·오탐
- [ ] DDL 실행 성공률
- [ ] 시간·토큰

## 보고 양식

- [ ] 실행 ID·버전·결과·한계
