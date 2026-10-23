# Specton 웹

React + TypeScript + Vite. 화면 구성 라이브러리는 ADR-0005 결정 후 추가한다.

```bash
npm install
npm run dev     # http://localhost:5173 (/runs, /health는 FastAPI 8000으로 프록시)
npm run lint
npm run build
```

UI는 API만 호출하고 그래프나 DB를 직접 실행하지 않는다.
