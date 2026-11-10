# ADR-0005: 화면 라이브러리

- 날짜: 2026-10-23
- 상태: 제안
- 결정자: 팀 설계로 (회의에서 승인·수정·보류)

## 배경

웹은 React로 확정했다. 화면은 업로드·표·탭·승인 버튼 위주이고 기간이 짧다.

## 결정

- Ant Design을 쓴다. ERD는 브라우저에서 `mermaid` JS로 렌더링한다.
- UI는 API만 호출한다.

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
| shadcn/ui | 가볍고 디자인 자유 | 컴포넌트를 직접 조립 | 기간 대비 작업량 |
| MUI | 성숙, DataGrid | 고급 표 기능 일부 유료 | 표 중심 화면에 제약 |
| Mantine | 빠른 MVP | 생태계가 작음 | Ant Design 대비 이점 적음 |

## 검토 근거

조사일 2026-10-23. 공개 비교 자료 기준이다.

| 후보 | 강점 | 약점 | 적합도 |
|---|---|---|---|
| Ant Design | 표·폼·단계(Steps)·탭 등 데이터 중심 컴포넌트가 풍부 | 무겁고 고유 디자인 | 검토·표 위주 화면에 가장 적합 |
| shadcn/ui | 가볍고 자유로운 디자인, Tailwind | 컴포넌트를 직접 조립 | 디자인 중시·프런트엔드 경험자가 있을 때 |
| MUI | 성숙, DataGrid | 고급 표 기능 일부 유료 | 무난 |
| Mantine | 빠른 MVP 개발 | 생태계가 상대적으로 작음 | 무난 |

출처: [shadcn vs MUI vs Ant Design](https://adminlte.io/blog/shadcn-ui-vs-mui-vs-ant-design/) · [React UI libraries 2026](https://www.thebcms.com/blog/react-ui-libraries/)

## 추가 결정 (2026-11-10, #281·#282)

개발용 AI Workspace(`/workspace`)의 실행 단계 그래프·ERD 캔버스·문서 추적은 노드 캔버스로 그린다.

- React Flow(`@xyflow/react`)로 노드·선·확대·미니맵·키보드 조작을 쓴다.
- 배치는 elkjs(ELK `layered`, 위→아래)로 한다. 서버 PDF ERD 개요(#273)와 같은 엔진·방향이다.
- 두 라이브러리는 `/workspace`에서만 불러온다(lazy·dynamic import). 첫 화면과 UI-00~07 번들에는 들어가지 않는다.
- 기존 화면의 Ant Design·Mermaid 결정은 바꾸지 않는다.

### 서드파티 라이선스

웹 번들로 브라우저에 배포되는 라이브러리라 고지한다. 모두 수정하지 않고 공개 npm 패키지 그대로 쓴다.

| 패키지 | 버전 | 라이선스 | 비고 |
|---|---|---|---|
| `elkjs` | 0.12.1 | EPL-2.0 OR GPL-3.0-or-later | **EPL-2.0을 택한다**(#282 R1 결정). 소스: https://github.com/kieler/elkjs |
| `@xyflow/react`, `@xyflow/system` | 12.12.1 | MIT | https://github.com/xyflow/xyflow |
| `zustand`, `classcat`, `use-sync-external-store` | lock 기준 | MIT | React Flow 하위 패키지 |

## 결과

- 좋아지는 점: 표·폼·단계·탭 컴포넌트를 바로 쓸 수 있다.
- 감수할 점: 번들이 무겁고 고유 디자인을 따른다.
- 관련 문서: [09 화면](../09-ui-flow.md)
