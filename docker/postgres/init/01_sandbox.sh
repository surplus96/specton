#!/usr/bin/env bash
# DDL 검증 전용 DB와 제한 역할을 만든다. 이 역할은 specton_app에 접속할 수 없다.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname specton_app \
  -v sandbox_password="$SANDBOX_PASSWORD" <<'SQL'
CREATE ROLE specton_sandbox LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'sandbox_password';
CREATE DATABASE specton_sandbox OWNER specton_sandbox;
REVOKE CONNECT ON DATABASE specton_app FROM PUBLIC;
ALTER ROLE specton_sandbox SET statement_timeout = '10s';
SQL
