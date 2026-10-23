# Specton web

[![한국어](https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-lightgrey)](README.md) [![English](https://img.shields.io/badge/lang-English-1f6feb)](README.en.md)

React + TypeScript + Vite. The UI component library will be added after ADR-0005 is decided.

```bash
npm install
npm run dev     # http://localhost:5173 (/runs and /health are proxied to FastAPI on 8000)
npm run lint
npm run build
```

The UI only calls the API; it never runs the graph or the DB directly.
