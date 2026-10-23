# Specton 웹

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-1f6feb)](README.md) [![English](https://img.shields.io/badge/lang-English-lightgrey)](README.en.md)

React + TypeScript + Vite. 화면 구성 라이브러리는 ADR-0005 결정 후 추가한다.

```bash
npm install
npm run dev     # http://localhost:5173 (/runs, /health는 FastAPI 8000으로 프록시)
npm run lint
npm run build
```

UI는 API만 호출하고 그래프나 DB를 직접 실행하지 않는다.
