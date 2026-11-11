# 도메인 팩

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
  RATIONALE.md                 ✍ 공통표준 단어·도메인·명명·진단·타입 프로필 근거
  words.yaml                   ⚙ 팩들이 쓰는 공식 단어 + 공식 분류어 전체
  domains.yaml                 ⚙ 팩들이 쓰는 공식 도메인 (PostgreSQL 매핑 포함)
  pack.lock                    ⚙ version별 팩 내용 sha256 기록
inventory/ · maintenance/
  manifest.yaml                ✍
  term_specs.yaml              ✍ 용어명·구성 단어·도메인·동의어
  terms.yaml                   ⚙ 물리명·출처(official/project) 확정
  words.yaml                   ✍ 공통표준에 없는 팩 전용 단어 + common/words.yaml에 오르지 않는 공통표준 단어
  patterns.yaml                ✍
  standard_selection.yaml      ✍ 공식 이음동의어·금칙어 선별 적용 (있을 때만)
  examples/A01.yaml … A09.yaml ✍ 에이전트별 few-shot 예시 (각 에이전트 담당 소유)
  pack.lock                    ⚙ version별 팩 내용 sha256 기록
  RATIONALE.md                 ✍ 팩 자료 선택 근거 (maintenance)
```

## 작업 방법

운영 확장 어휘는 `inventory/lexicon_sources.yaml`에 기준 사전·공개 CSV 사본·포함/제외 근거를
기록하고 manifest.lexicon_sources로 선언한다(#291). build·loader가 동일한 형식·행·해시 검증을
수행한다. 원본은 inventory/sources 아래에 두며 CP949 CSV 바이트를 변환하지 않는다.
자세한 형식과 기존 팩 호환은 [문서 입출력·팩](../docs/10-io-and-packs.md)을 따른다.

```bash
uv run python -m specton.packs.build          # ✍ 입력을 고친 뒤 ⚙ 파일 재생성
uv run python -m specton.packs.build --check  # ⚙ 파일이 최신인지 검사 (CI에서 실행)
```

- 생성기는 분류어로 끝나는지, 분류어와 도메인이 맞는지, 물리명 63바이트, 물리명 중복을 검사하고 어기면 실패한다.
- 팩 내용이 바뀌면 해당 `manifest.yaml`의 `version`을 올린다. 평가 전에는 `status: approved`로 고정한다.
- few-shot 예시는 개발용 세트에서만 만든다 ([07 테스트·평가](../docs/07-testing-eval.md#평가-데이터)).
  - `input`에는 개발용 세트의 요구사항 문장을 그대로 쓸 수 있다. 개발용 세트는 공개 기능 문서를 참고해 팀이 새로 쓴 합성 자료라 라이선스 제약이 없다 (PR #66 리뷰).
  - 예시마다 그 예시에 필요한 요구사항 몇 건만 넣고 `source_id`에 원문 ID를 적는다.
  - `output`은 담당자가 노드 출력 모델에 맞춰 직접 쓴다. 참고용 기대 결과를 그대로 옮기지 않는다.
  - 넣지 않는 것: 개발용 세트 전체, 참고용 기대 결과(기능 명세서·ERD·DDL·RTM) 원본, 외부 제품의 문서 문장·코드·DB 덤프, 평가용 세트 문서.
- 공통표준 판 교체: `sources/`의 CSV를 바꾸고 `sources.yaml`을 고친 뒤 재생성한다.
- 작업 방법: 팩 폴더의 `.yaml`(예시 포함) 중 하나라도 고치면 그 팩의 `manifest.yaml`에서 `version`을 먼저 올리고, 그다음 재생성한다. `pack.lock`은 `versions: {버전: sha256}` 기록이라 지난 버전도 남는다. 버전을 올리지 않고 내용만 바꾼 채 재생성하면 같은 버전에 다른 해시가 걸려 생성 자체가 실패하고(`BuildError`), 버전만 올리고 재생성을 하지 않으면 `pack.lock`에 새 버전 항목이 없어 `--check`가 실패한다.
- `manifest.yaml`의 `status`를 `draft`에서 `approved`로 바꾸는 것도 내용이 바뀐 것이라 `version`을 함께 올려야 한다.
- `--check`가 이 에러로 실패하면 해당 팩의 `manifest.yaml`에서 `version`을 올리고 다시 생성한다.

## 재고·공통 팩 고정 (#11, 2026-11-09)

현재 범위는 common 0.1.5·inventory 0.1.21(approved)이다. 설비 팩은 후속으로 유지한다.
처리 방식은 `common/rules.yaml`의 `handling`으로 명시한다. fixed만 target_stage가 있으며,
dynamic·manual·informational의 null은 미정값이 아니다. SC critical과 major 참고 의견은 거절한다.
선별 적용에는 낱말·표준어·사유를 모두 적고, 목록에 없는 공식 이음동의어·금칙어 등록은 금지한다.
정리 모델·manifest는 공통 버전과 전체 팩·출처의 정책 해시를 보존한다. 자세한 결정은 ADR-0009를 따른다.
