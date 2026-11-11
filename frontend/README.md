# Specton 웹

React + TypeScript + Vite. 자체 React·CSS 컴포넌트로 F안 디자인 시스템 v0.2를 구현한다(ADR-0005, #332·#334).

```bash
npm install
npm run dev     # http://localhost:5173 (/runs, /health는 FastAPI 8000으로 프록시)
npm run lint
npm run build
```

UI는 API만 호출하고 그래프나 DB를 직접 실행하지 않는다.

로컬 실제 연동 화면은 `http://localhost`로 통일한다. 현재 작업 폴더의 프런트엔드를
프로덕션 모드로 빌드하고 Caddy가 `/runs`·`/health`를 실제 API에 전달한다.

```bash
# 저장소 루트에서 실행. 기존 DB·저장 볼륨은 유지한다.
docker compose -f compose.deploy.yml -f compose.local.yml --env-file .env.deploy build api web
docker compose -f compose.deploy.yml -f compose.local.yml --env-file .env.deploy up -d
```

이 구성에서 5194·5196은 localhost로 이동하는 이전 주소다. 해당 포트의 Vite 서버는 함께
실행하지 않는다. HTML은 재검증하고 해시 파일명 자산만 장기 캐시한다. 이미 열린 예전 탭은
새로고침해야 한다. `dev:mock`은 별도 UI 시험용이며 위 실제 연동 구성에서 시작하지 않는다.

기본 배포는 Caddy/Vite 프록시를 통한 같은 출처 API이다. `VITE_API_BASE_URL`을 지정하면 HTTP와 SSE 모두 세션 쿠키를 포함하지만, 다른 출처 배포에는 서버 CORS 허용과 쿠키 SameSite·Secure 정책도 필요하다. 현재 기본 백엔드는 이 구성을 제공하지 않으므로 같은 출처 프록시를 권장한다.

UI 진단 보완(2026-11-12): `npm test`는 단계 표시·산출물 존재·서버 CSV·목업 manifest 계약을 검사한다. 목업 시연은 `npm run dev:mock`으로 기동하며 실제 LLM을 호출하지 않는다. Pretendard Variable v1.3.9는 `public/fonts/`에서 로컬 제공하고 SIL OFL 1.1 고지는 `public/fonts/OFL.txt`에 보존한다. 디자인 색 값은 `src/index.css :root`를 수정한다.

첨부 진단의 미확인 제안 처리: revision 0은 실제 API의 초기 산출물 버전이므로 유지한다. F안 원본 대조 자료가 없는 버튼 모양은 유지한다. 시작 화면 순서도 유지하고 목록 이름을 「최근 작업」으로 바로잡았다. 단계 표시의 작업공간은 「지남」 대신 「결과 있음」으로 표현한다.
