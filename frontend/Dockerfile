# Specton 웹 이미지 (#25, ADR-0013). 웹 화면을 빌드해 Caddy로 서빙하고 API 요청은 api 컨테이너로 넘긴다.
# mock은 개발 모드(--mode mock)에서만 켜지므로 이 빌드에는 들어가지 않는다 (src/main.tsx).
#
#   빌드: docker build -t specton-web frontend
#   설정: docker/web/Caddyfile (compose.deploy.yml이 붙인다)

ARG NODE_IMAGE=node:22-bookworm-slim
ARG CADDY_IMAGE=caddy:2.10-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM ${CADDY_IMAGE}
COPY --from=build /web/dist /srv
