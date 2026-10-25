<!-- PR 제목: <type>: <내용> (이슈 번호는 넣지 않는다. 병합 시 (#PR번호)가 자동으로 붙는다) -->
Closes #

## 변경 내용

- 문제:
- 변경된 동작:

## 관련 항목

- REQ / docs 문서 / TC / ADR:

## 영향 확인

- [ ] `specton/contracts/` 변경 없음 (있으면 `contract-change` 라벨, 2인 승인)
- [ ] 의존성 변경 없음 (있으면 lock 파일만 담은 단독 PR)
- [ ] `domain_packs/` 입력을 바꿨다면 `uv run python -m specton.packs.build` 결과를 포함하고 `manifest` version을 올림
- [ ] DB·실제 LLM 테스트가 필요한 변경이면 `db`·`llm` 라벨을 붙이고 수동 실행 결과를 아래에 적음
- [ ] 설계 결정이 바뀌었다면 ADR을 추가·갱신함

## 테스트

```text
실행한 명령과 결과
```

## 미정·실패 사항

-
