# Specton 웹

React + TypeScript + Vite. 자체 React·CSS 컴포넌트로 F안 디자인 시스템 v0.2를 구현한다(ADR-0005, #332·#334).

```bash
npm install
npm run dev     # http://localhost:5173 (/runs, /health는 FastAPI 8000으로 프록시)
npm run lint
npm run build
```

UI는 API만 호출하고 그래프나 DB를 직접 실행하지 않는다.

기본 배포는 Caddy/Vite 프록시를 통한 같은 출처 API이다. `VITE_API_BASE_URL`을 지정하면 HTTP와 SSE 모두 세션 쿠키를 포함하지만, 다른 출처 배포에는 서버 CORS 허용과 쿠키 SameSite·Secure 정책도 필요하다. 현재 기본 백엔드는 이 구성을 제공하지 않으므로 같은 출처 프록시를 권장한다.
