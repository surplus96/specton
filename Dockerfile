# Specton API 실행 이미지 (#25, ADR-0013). 로컬과 AWS가 같은 이미지를 쓴다.
#
# 담는 것: Python 3.12 앱, WeasyPrint용 Pango, 한글 폰트(Noto Sans CJK), mermaid-cli, Chromium.
# 웹 화면(frontend/)은 이 이미지에 넣지 않는다. API는 웹 파일을 서빙하지 않는다.
#
# mermaid-cli는 ADR-0004에 고정한 이미지에서 설치 파일과 잠금 파일만 가져와 Debian에서 다시 설치한다.
# 그 이미지는 Alpine(musl)·Python 3.11이라 그대로 쓸 수 없다(rhwp-python은 musl 휠이 없고, 앱은 3.12).
# 같은 잠금 파일로 설치하므로 안의 mermaid는 웹과 같은 11.17.2다.
#
#   빌드: docker build -t specton-api .   (마지막 단계 release = runtime, 테스트 파일 없음)
#   검사: docker build --target check .   (PDF·ERD 테스트를 이미지 안에서 돌린다)

# 바탕 이미지는 다이제스트로 고정한다 (#226 리뷰). apt 패키지(Chromium·Pango)는 빌드 시점 판이므로,
# 배포는 한 번 만든 이미지를 그대로 옮겨 「로컬과 AWS가 같은 이미지」를 지킨다 (#25).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
ARG MERMAID_CLI_IMAGE=minlag/mermaid-cli:11.16.1@sha256:d98fe54c22e78e65335589fc17d5419f698f915cebca48ea21fee633aff8b258

# ── mermaid-cli: 고정 이미지의 설치 파일·잠금 파일로 다시 설치 ─────────────
FROM ${MERMAID_CLI_IMAGE} AS mermaid-source

FROM ${NODE_IMAGE} AS mermaid
# 잠금 파일이 ../../install/*.tgz를 가리키므로 원래 경로를 그대로 쓴다.
COPY --from=mermaid-source /install /install
COPY --from=mermaid-source /home/mermaidcli/package.json /home/mermaidcli/package-lock.json /home/mermaidcli/
WORKDIR /home/mermaidcli
# 브라우저는 내려받지 않고 Debian Chromium을 쓴다 (puppeteer.json).
ENV PUPPETEER_SKIP_DOWNLOAD=true
RUN npm ci --omit=dev --no-audit --no-fund \
 && node -e "const v=require('mermaid/package.json').version; if (v !== '11.17.2') { console.error('mermaid ' + v + ' != 11.17.2'); process.exit(1) }"

# ── Python 의존성 (uv.lock 그대로) ──────────────────────────────────────
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY specton ./specton
RUN uv sync --locked --no-dev

# ── 실행 이미지 ─────────────────────────────────────────────────────────
FROM ${PYTHON_IMAGE} AS runtime
# Pango: WeasyPrint. fonts-noto-cjk: "Noto Sans CJK KR"(specton/export/pdf.py FONT_FAMILY).
# chromium: mermaid-cli가 SVG를 그린다. libstdc++6: node 실행 파일.
# tini: PID 1로 끝난 자식 프로세스를 회수한다. 없으면 mmdc가 남긴 Chromium 보조 프로세스가
# 좀비로 쌓인다(#226 리뷰 재현: ERD 3번에 좀비 12개 → tini로 0개).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-noto-cjk chromium libstdc++6 ca-certificates tini libfreetype6 \
 && rm -rf /var/lib/apt/lists/*

# rhwp-python 0.8.1 리눅스 휠이 묶은 libfreetype에 함수가 빠져 `import rhwp`가 실패한다
# (amd64 FT_Palette_Data_Get, arm64 FT_Palette_Select. 상류 DanMeon/rhwp-python #31, #25 R1 요청).
# 시스템 libfreetype을 먼저 불러오면 된다. 경로가 아키텍처마다 달라 빌드 때 고정 경로로 링크한다.
# 상류가 고쳐져 rhwp-python을 올리면 이 링크와 LD_PRELOAD를 지운다.
RUN ln -s "$(dpkg -L libfreetype6 | grep '/libfreetype\.so\.6$')" /usr/local/lib/libfreetype-preload.so.6 \
 && test -e /usr/local/lib/libfreetype-preload.so.6

COPY --from=mermaid /usr/local/bin/node /usr/local/bin/node
COPY --from=mermaid /home/mermaidcli/node_modules /opt/mermaid-cli/node_modules
COPY docker/api/puppeteer.json /app/config/puppeteer.json

RUN useradd --create-home --uid 10001 specton \
 && mkdir -p /data/storage && chown specton:specton /data/storage

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY specton ./specton
COPY domain_packs ./domain_packs

ENV PATH="/app/.venv/bin:/opt/mermaid-cli/node_modules/.bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    SPECTON_STORAGE_DIR=/data/storage \
    SPECTON_PACK_ROOT=/app/domain_packs \
    SPECTON_MERMAID_PUPPETEER_CONFIG=/app/config/puppeteer.json \
    LD_PRELOAD=/usr/local/lib/libfreetype-preload.so.6

USER specton
EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "specton.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── 검사용: 이미지 안에서 PDF·ERD 테스트 (배포 이미지에는 들어가지 않는다) ──────
FROM runtime AS check
USER root
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY tests ./tests
RUN UV_PYTHON_DOWNLOADS=never uv sync --locked \
 && chown -R specton:specton /app
USER specton
ENV SPECTON_MMDC_PUPPETEER=/app/config/puppeteer.json
# mmdc가 PATH에 없으면 실제 mermaid-cli 시험이 건너뛰기로 끝나므로 먼저 막는다 (#226 리뷰).
# libfreetype 선로드가 빠지면 rhwp import가 실패하므로 여기서 막는다 (#25 R1 요청).
RUN mmdc --version && python -c "import rhwp" && pytest -q -rs tests/unit/test_pdf_engine.py tests/unit/test_pdf_adapter.py \
      tests/unit/test_erd.py tests/unit/test_erd_areas.py tests/unit/test_erd_node.py

# ── 기본 빌드 대상: 실행 이미지 (마지막 단계가 기본이라 check 뒤에 둔다) ─────
FROM runtime AS release
