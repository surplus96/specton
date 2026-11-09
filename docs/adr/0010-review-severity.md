# ADR-0010: 검토 심각도

- 날짜: 2026-10-23 (승인 2026-10-27, SC 예외 추가 2026-11-09)
- 상태: 승인
- 결정자: 팀 설계로 (#9 착수 시 R1 승인)

## 배경

규칙 검사와 LLM 지적의 심각도, 자동 재작업 조건이 정해지지 않았다. LLM 지적에는 오탐이 섞인다.

## 결정

- 규칙 위반은 `critical`(차단). LLM 지적은 `major`/`minor`.
- 자동 재작업은 `critical`과 `major`만. `minor`는 참고 의견으로 HITL 2에 표시한다.
- 미해결 `critical`이 있으면 승인 완료로 표시하지 않는다.
- 예외 (#15, 2026-11-09): 표준 준수 지적 SC-01~06은 규칙 지적(`source=rule`)이지만 `critical`을 쓰지 않는다. 심각도는 `domain_packs/common/rules.yaml`에서 읽는다(SC-01·02 `minor` 참고, SC-03·06 `major` 데이터 설계 재작업, SC-04 금칙어·SC-05 `major` 사람 조치). SC-02·03은 R1이 확인한 값이고, SC-01·04·05·06은 제안값으로 임시 반영했다(R1·R2 최종 확인 전). SC-04 이음동의어는 아직 지적하지 않는다(후속). 표준 고시는 적용이 어려우면 선별 적용을 허용한다(제8조⑤·제10조⑤, `common/RATIONALE.md`).
- 구현: 자동 재작업 기준은 `specton/review/rework.py`의 `AUTO_REWORK_SEVERITIES`(#9). LLM 출력(`FindingDraft`)은 `critical`을 거절하고, `Finding`은 규칙 지적만 `critical`을 허용한다(#68).

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
| LLM 지적도 critical 허용 | 중대한 의미 오류 차단 | 오탐으로 재작업 폭증 | 오탐 위험 |
| 모든 지적을 HITL로 | 사람이 판단 | 자동 재작업 이점 상실 | 사용자 부담 |

## 결과

- 좋아지는 점: 오탐이 자동 루프를 지배하지 않는다.
- 감수할 점: LLM이 찾은 중대 결함이 `major`로 남을 수 있다.
- 관련 문서: [04 에이전트](../04-agents.md), `domain_packs/common/rules.yaml`
