# A08 별도 탐색 사전 준비 (#20)

고정된 승인 팩으로 정리할 수 없는 A08 사례를 별도 조건으로 준비하는 오프라인 도구다. `compose_lexicon`은 LLM·DB·네트워크를 호출하지 않는다. 기준 팩·출처 파일을 새 폴더에 복사하고 추가 단어를 별도 JSON에 보관한다. 운영 팩의 manifest·words·lock·few-shot은 바꾸지 않는다.

이 도구는 [평가 범위](07-testing-eval.md#검토-관점-평가)에서 정한 사전 합성 기능의 공백을 채운다. 승인된 고정 설계·정답이나 실제 검토자의 의미 판단·출처 이용 조건 확인을 대신하지 않는다. 평가 관측을 보고 선정한 어휘는 관측 후 탐색이며 블라인드 평가나 운영 팩의 독립 보완으로 보고하지 않는다.

## 입력 형식

입력·원본 CSV·승인·사본·결과는 팀 비공개 위치에 둔다. 공개 저장소에는 합성 테스트만 남긴다. 실제 JSON 모델은 `specton/evaluation/lexicon_overlay.py`의 `OverlaySpec`이다.

| 필드 | 내용 |
|---|---|
| `schema_version`, `scope` | `1`, `evaluation_exploration` |
| `condition_id`, `dictionary_version` | 본 평가와 구분할 조건 ID·확장 사전 버전 |
| `pack` | 기준 도메인 팩 이름 |
| `base_pack_version`, `base_common_version`, `base_policy_digest` | 승인 기준을 선정 전에 고정한 버전·정책 해시 |
| `sources` | 출처별 상대경로·원본 SHA-256·판·발행처·HTTPS URL·이용 조건·확인 날짜·인코딩·CSV 열 이름 |
| `additions` | 단어 값과 출처 ID·행 번호·선정 근거(`selection_reason`)·의미/설명 근거(`definition_basis`) |

`sources`는 운영 출처 검증과 같은 `Source` 형식을 사용한다. `hash_mode: raw_bytes`, `license: 이용허락범위 제한 없음`, `encoding: cp949` 또는 `utf-8-sig`, `word_column`·`english_column`·`abbreviation_column`이 필요하다. URL은 기록만 하며 다운로드하지 않는다. 실제 이용허락과 의미는 검토자가 원본·조건을 확인한다.

추가 단어의 `word` 객체는 기존 `Word` 형식(한글 `word`·`english`·`abbreviation`·`definition`·`is_classifier` 등)이다. 한글·영문·약어가 해당 출처 CSV 행과 일치해야 한다. CSV 첫 데이터 행은 2다. 현재 합성은 영문 대문자로 시작하는 대문자/숫자/밑줄 약어와 기준 팩의 약어 길이 제한을 사용한다.

다음 입력은 거절한다.

- 기존에 등록되거나 사전으로 조합 가능한 이름, NFC 기준 중복 단어, 기존/추가 단어와 겹치는 약어
- 자유 별칭·금칙어·분류어·도메인/타입 정책 추가
- 출처 누락·행/값/원본 해시 불일치·사용하지 않는 출처·폴더 밖을 가리키는 출처 경로
- 기준 팩의 승인·버전·pack.lock·policy_digest 불일치
- 기준 팩 안의 출력 경로·이미 존재하는 출력·사본을 운영 팩으로 연결하는 symlink

## 사본 생성과 승인 기록

```bash
uv run python -m specton.evaluation.compose_lexicon /비공개/spec.json \
  --pack-root domain_packs --out /비공개/draft-lexicon
```

출력 폴더에는 `base/`의 변경 없는 기준 사본, `sources/`의 추가 출처 CSV, 선정 내용과 `subject_sha256`을 담은 `overlay.json`이 생긴다. JSON의 출처 경로는 사본 내부 경로로 정규화하므로 같은 선정·원본·기준으로 다른 위치에 사본을 만들어도 선정 해시는 같다. 승인 없이 만든 사본은 `ready_to_run: false`이며 실행 경로에서 거절한다. 기존 파일/폴더를 덮어쓰지 않는다.

R1·R4는 추가 어휘·선정 이유·의미·출처/이용 조건·기준 해시와 별도 탐색 범위를 검토한 뒤 아래 형식의 비공개 승인 기록을 제공한다. 자리표시자를 실제 검토 기록으로 바꿔야 하며, 도구가 승인 기록을 만들어 주지는 않는다.

```json
{
  "subject_sha256": "<overlay.json의 subject_sha256>",
  "reviews": [
    {"role": "R1", "reviewer": "<검토자>", "decision": "approved", "reference": "<실제 검토 기록>"},
    {"role": "R4", "reviewer": "<검토자>", "decision": "approved", "reference": "<실제 검토 기록>"}
  ]
}
```

두 역할이 각각 한 번 있어야 하고 대상 해시가 정확히 같아야 한다. 단어·선정 근거·출처·사전 버전 등을 바꾸면 이전 승인을 재사용할 수 없다. 승인 JSON은 신뢰할 수 있는 팀 검토 기록에서 가져와야 한다. 도구는 역할·대상 해시·기록 형식을 확인하며 검토자 신원을 인증하거나 실제 검토 내용을 판정하지 않는다.

```bash
uv run python -m specton.evaluation.compose_lexicon /비공개/spec.json \
  --pack-root domain_packs --out /비공개/reviewed-lexicon \
  --reviews /비공개/reviews.json
```

기준 팩 버전은 그대로 남고 `dictionary_version`은 별도 확장 사전 버전이다. 합성 사전의 `lexicon_digest`와 승인 기록까지 묶은 탐색 `policy_digest`는 기준과 구분된다. 출처·기준 파일·선정 해시와 승인 기록이 맞지 않으면 생성 또는 실행을 거절한다.

## 명시적인 A08 탐색 실행

아래 명령은 실제 LLM 호출이므로 기존 예산·원문 외부 전송 승인이 있는 범위에서 실행한다. 사전 승인과 실제 API 호출 승인은 별도다.

```bash
uv run python -m specton.review.eval_fixtures /비공개/a08-fixed.yaml \
  --lexicon-overlay /비공개/reviewed-lexicon \
  --out /비공개/a08-exploration-new.json
```

이 옵션은 A08에서만 지원한다. 별도 사본의 기준 팩·few-shot을 사용하고 실제 정리 코드에 합성 사전을 명시적으로 주입한다. 모든 사례가 명시적 속성과 정리 진입 조건을 통과한 뒤 첫 호출을 시작한다. 승인 누락·정리 실패는 자료 오류이며 미탐이나 지적 0건으로 바꾸지 않는다. 이후 호출 전에도 사본 무결성을 확인한다. 사례 전체의 기존 토큰 예산과 실패 기록을 유지한다.

결과에는 `evaluation_scope: exploration`, 조건 ID·확장 사전 버전·기준 정책 해시·선정 해시·R1/R4 검토 참조와 정리 사전/정책/모델 해시를 남긴다. 고정 평가나 다른 탐색 조건의 결과를 한 보고서에 합산하면 거절한다. 결과 파일은 새 경로에만 쓰며, 기존 경로이면 client를 만들기 전에 거절한다. 결과에는 지적과 평가 자료가 있으므로 비공개로 보관한다.

옵션을 생략한 기존 평가 경로는 고정된 승인 사전만 사용한다. 이 도구의 합성 시험 통과는 실제 평가 어휘·고정 설계의 승인, #20의 팩 적용/미적용 비교, 기능/모델 채점, #22 전체 릴리스 후보 확정을 뜻하지 않는다.
