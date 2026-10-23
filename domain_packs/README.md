# 도메인 팩

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-1f6feb)](README.md) [![English](https://img.shields.io/badge/lang-English-lightgrey)](README.en.md)

Specton 실행 **전에** 준비하는 입력이다. 실행 중에는 읽기만 하고, 실행 결과물(요구사항·ERD·DDL 등)은 여기에 쓰지 않는다.

## 파일 구분

| 표시 | 의미 | 수정 방법 |
|---|---|---|
| ✍ | 사람이 작성 | 직접 수정 → PR |
| ⚙ | 생성 파일 (맨 위 `GENERATED` 표시) | 직접 수정 금지. 입력을 고치고 다시 생성 |

```text
sources/                       ✍ 공식 공통표준 CSV 사본 + sources.yaml (판·출처)
common/
  manifest.yaml naming.yaml rules.yaml   ✍
  words.yaml                   ⚙ 팩들이 쓰는 공식 단어 + 공식 분류어 전체
  domains.yaml                 ⚙ 팩들이 쓰는 공식 도메인 (PostgreSQL 매핑 포함)
inventory/ · maintenance/
  manifest.yaml                ✍
  term_specs.yaml              ✍ 용어명·구성 단어·도메인·동의어
  terms.yaml                   ⚙ 물리명·출처(official/project) 확정
  words.yaml                   ✍ 공통표준에 없는 팩 전용 단어
  patterns.yaml                ✍
  examples/A01.yaml … A09.yaml ✍ 에이전트별 few-shot 예시 (각 에이전트 담당 소유)
```

## 작업 방법

```bash
uv run python -m specton.packs.build          # ✍ 입력을 고친 뒤 ⚙ 파일 재생성
uv run python -m specton.packs.build --check  # ⚙ 파일이 최신인지 검사 (CI에서 실행)
```

- 생성기는 분류어로 끝나는지, 분류어와 도메인이 맞는지, 물리명 63바이트, 물리명 중복을 검사하고 어기면 실패한다.
- 팩 내용이 바뀌면 해당 `manifest.yaml`의 `version`을 올린다. 평가 전에는 `status: approved`로 고정한다.
- few-shot 예시는 개발용 세트에서만 가져오고 `source_id`에 원문 ID를 적는다. 평가용 세트 문서는 넣지 않는다.
- 공통표준 판 교체: `sources/`의 CSV를 바꾸고 `sources.yaml`을 고친 뒤 재생성한다.
