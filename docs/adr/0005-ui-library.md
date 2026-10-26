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

## 결과

- 좋아지는 점: 표·폼·단계·탭 컴포넌트를 바로 쓸 수 있다.
- 감수할 점: 번들이 무겁고 고유 디자인을 따른다.
- 관련 문서: [09 화면](../09-ui-flow.md)
