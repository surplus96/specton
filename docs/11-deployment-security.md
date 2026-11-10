# 배포·운영·보안

> 상태: **초안** (AWS 구성은 ADR-0013 승인, 2026-11-09)

## 실행 환경

| 구성 | 용도 | 접근 경계 |
|---|---|---|
| FastAPI·실행기 | 실행 제어·노드 수행 | 서버 세션의 실행 소유권 검사 |
| 웹 UI | 입력·HITL·출력 | API만 호출 |
| `specton_app` DB | 실행·문서·승인·체크포인트 | 앱 계정, 비밀 로그 금지 |
| `specton_sandbox` DB | 생성 DDL 검증 | 제한 계정·허용 문장·시간 제한 |
| 파일 저장소 | 원문·추출본·출력 | `storage_ref`로 접근, 파일명을 경로로 쓰지 않음 |

- 로컬: `docker compose up -d db` (PostgreSQL 18, 127.0.0.1에만 노출). 초기화 스크립트는 `docker/postgres/init/`.
  - 초기화 스크립트는 DB 볼륨을 처음 만들 때만 돈다. 격리 DB(`specton_sandbox`)를 만드는 `01_sandbox.sh`는 #171(2026-11-08)에서 들어왔으므로, 그 전에 만든 개발 DB 볼륨에는 격리 DB·역할이 없어 SQL 검증이 연결 오류(`error`)로 끝나고 실행이 실패한다. 볼륨을 지우고 다시 만들면(`docker compose down -v` 뒤 `up -d db`, 개발 DB 내용은 사라짐) 생긴다.
  - `*.sh`는 `.gitattributes`로 LF를 쓴다(#171). 그 전에 받은 Windows 작업 폴더는 `01_sandbox.sh`가 CRLF로 남아 bash가 실패할 수 있다. 파일을 지우고 `git checkout -- docker/postgres/init/01_sandbox.sh`로 다시 받으면 LF가 된다.
  - Windows Docker Desktop에서는 DB 주소를 `localhost`가 아닌 `127.0.0.1`로 쓴다(`.env.example` 기본값). 아래 「격리 DB (sandbox)」의 IPv6 설명과 같은 원인이다.
- 로컬과 AWS는 같은 컨테이너 이미지를 쓴다. PDF 렌더러 의존성·한글 폰트·모델 다운로드를 이미지에 포함한다.
- 배포 구성 (#25): `compose.deploy.yml`이 db·api(`Dockerfile`)·web(`frontend/Dockerfile`, Caddy)을 띄운다.
  밖으로 여는 포트는 web의 80·443뿐이고 db·api는 내부 네트워크에만 둔다. web이 `/runs`·`/health`를 api로 넘기고
  나머지는 웹 화면이다(`docker/web/Caddyfile`). `SPECTON_SITE_ADDRESS`에 도메인을 넣으면 HTTPS 인증서를 자동으로 받는다.
  비밀값(`POSTGRES_PASSWORD`·`SANDBOX_PASSWORD`·`SPECTON_OPENAI_API_KEY`)은 `.env.deploy`로 주입하며 기본값이 없어
  비어 있으면 기동하지 않는다(`.env.deploy.example`). 개발용 `docker-compose.yml`은 DB만 127.0.0.1에 띄우는 그대로 둔다.
- 같은 이미지 보장 (#226 리뷰): 이미지는 한 곳에서 한 번 빌드해 레지스트리에 올리고(`compose build`·`push`), 서버는
  `pull` 뒤 `up -d --no-build`로 받은 이미지를 그대로 쓴다. 서버에서 다시 빌드하지 않는다. 이름·태그는
  `SPECTON_API_IMAGE`·`SPECTON_WEB_IMAGE`(예: `ghcr.io/<owner>/specton-api:<커밋>`). 서버가 x86_64면 amd64로 빌드한다.
- AWS (ADR-0013 승인): EC2 1대(서울) + Docker Compose, 키는 환경 변수 주입, 예산 알림. 보안 그룹은 80번 전체 공개(Caddy 인증서 발급·HTTPS로 넘기기만), 443번은 팀·시연 장소 IP만, 22번은 팀 IP만 또는 닫고 SSM. HTTPS에는 도메인(`SPECTON_SITE_ADDRESS`)이 필요하다. App Runner는 신규 고객을 받지 않아 제외.
- 배포 전 할 일: compose의 DB 기본 비밀번호를 없애고 환경 변수를 필수로 받는다. → 배포 구성(`compose.deploy.yml`)에 반영 (#25)

### 배포 절차 주의 (#25, #228 리뷰)

- **`--env-file .env.deploy`를 명령마다 붙인다. 서버에는 `.env`를 두지 않는다.** 빠뜨리면 compose가 같은 폴더의
  `.env`를 읽는다. 개발용 `.env`(`.env.example`을 복사한 것)에는 DB 비밀번호 값이 있어 필수값 검사가 통과하고,
  그 비밀번호로 배포 DB가 만들어진다.
- **이미지는 서버 CPU에 맞춰 빌드한다.** compose에 플랫폼 지정이 없어 Apple Silicon에서 빌드하면 arm64 이미지가 올라간다.
  서버가 x86_64면 빌드하는 곳에서 `DOCKER_DEFAULT_PLATFORM=linux/amd64`를 붙인다:
  `DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose -f compose.deploy.yml --env-file .env.deploy build`
- **서버 checkout은 이미지 태그와 같은 커밋으로 둔다.** `docker/web/Caddyfile`과 DB 초기화 스크립트(`docker/postgres/init/`)는
  이미지가 아니라 서버 checkout에서 붙는다. 이미지 태그를 커밋 해시로 붙이고(`…/specton-api:<커밋>`), 서버에서는
  `git checkout <커밋>` 뒤 `pull`·`up -d --no-build`를 실행한다.
- **DB 비밀번호는 볼륨을 처음 만들 때만 적용된다.** 나중에 `.env.deploy`만 바꾸면 DB 역할 비밀번호와 어긋나 api가 접속하지
  못한다. 바꿀 때는 DB 안에서 먼저 바꾸고, 그다음 `.env.deploy`를 고쳐 api를 다시 띄운다.
  1. `docker compose -f compose.deploy.yml --env-file .env.deploy exec db psql -U specton -d specton_app`
  2. psql에서 `\password specton`·`\password specton_sandbox`로 새 비밀번호 입력 (명령 기록에 비밀번호가 남지 않게 대화형으로)
  3. `.env.deploy`의 `POSTGRES_PASSWORD`·`SANDBOX_PASSWORD`를 같은 값으로 고친다
  4. `docker compose -f compose.deploy.yml --env-file .env.deploy up -d --no-build api` (바뀐 접속 URL로 api만 다시 만든다)

### 데이터 보존·백업·복구 (#25, R1 결정)

저장 위치는 `compose.deploy.yml`의 Docker named volume이다. 컨테이너를 바꿔도 볼륨은 남는다.

| 볼륨 | 컨테이너 경로 | 담는 것 |
|---|---|---|
| `pgdata` | db `/var/lib/postgresql` | 앱 DB(`specton_app`: 실행·문서·승인·체크포인트·세션)와 sandbox DB |
| `storage` | api `/data/storage` (`SPECTON_STORAGE_DIR`) | 업로드 원문·산출물 파일 (`storage_ref`) |
| `caddy_data`·`caddy_config` | web `/data`·`/config` | HTTPS 인증서·설정 (없어지면 다시 발급) |

- **`down -v`를 쓰지 않는다.** `-v`는 위 볼륨을 지워 DB·업로드·산출물이 모두 사라진다. 멈출 때는 `down`, 재배포는 `pull` 뒤 `up -d --no-build`.
- 재배포·컨테이너 교체 뒤 유지 확인 (로컬 compose에서 확인, 2026-11-09): 업로드 → `up -d --no-build --force-recreate`
  → `down` 뒤 `up -d --no-build`를 거쳐도 같은 세션 쿠키로 실행 상태·추출 원문(19건)·업로드 파일이 그대로 보였다.
- **백업** (DB와 파일을 같은 시점으로 맞추려고 api를 잠깐 멈춘다. `D`는 `docker compose -f compose.deploy.yml --env-file .env.deploy`):
  1. `$D stop api`
  2. `$D exec -T db pg_dump -U specton -d specton_app -Fc > specton_app-<날짜>.dump`
  3. `$D run --rm --no-deps -u 0 -v "$PWD:/backup" --entrypoint tar api czf /backup/storage-<날짜>.tgz -C /data/storage .`
  4. `$D start api`
  - `-u 0`: 실행 이미지는 UID 10001로 돌아 서버의 백업 폴더(예: UID 1000·755)에 쓰지 못한다. root로 묶는다
    (리눅스 볼륨으로 확인: `-u 0` 없이 `Cannot open: Permission denied`, 붙이면 성공, #244 R1 리뷰).
  - sandbox DB는 검증용이라 백업하지 않는다(초기화 스크립트로 다시 만든다).
  - **백업 파일도 고객 원문·세션을 담는다.** 「자료 수명주기」의 보존 기간·삭제 대상에 백업 사본을 넣어, 업로드를
    지울 때 백업도 함께 지운다. 서버 밖에 두되 접근을 막고 암호화한다(예: 비공개 S3 버킷 + 서버 측 암호화).
- **복구** (빈 볼륨에 되살리기, 같은 `.env.deploy`):
  1. `$D up -d --no-build --wait db` (초기화 스크립트가 역할·sandbox를 만든 뒤에 돌아온다)
  2. `$D exec -T db pg_restore -U specton -d specton_app --clean --if-exists --no-owner < specton_app-<날짜>.dump`
  3. `$D run --rm --no-deps -u 0 -v "$PWD:/backup:ro" --entrypoint tar api xzf /backup/storage-<날짜>.tgz -C /data/storage`
  4. `$D up -d --no-build`
  - 1단계 `--wait`: postgres는 초기화 스크립트가 도는 동안 임시 서버를 소켓으로만 띄운다. db healthcheck를 TCP
    (`pg_isready -h 127.0.0.1`)로 보게 해 초기화가 끝나야 healthy가 된다. 그 전에 `pg_restore`를 돌리면 임시 서버에
    붙었다가 끊길 수 있다 (#244 R1 리뷰). 빈 볼륨에서 `--wait`가 돌아온 직후 sandbox 역할·DB가 있는 것을 확인했다.
  - 3단계 `-u 0`: root로 풀면 묶을 때의 소유자(10001)가 그대로 살아난다(확인: 복구 뒤 앱 사용자가 쓰기 가능).
  - 로컬 확인 (2026-11-09): 위 백업을 빈 볼륨의 새 구성에 복구하니 같은 세션 쿠키로 같은 실행·추출 원문 19건·업로드 파일이 보였다.
    산출물 내려받기는 LLM 실행이 필요해 실제 LLM E2E(TC-F19) 때 함께 확인한다.
- **AWS (EC2):** 볼륨은 호스트 디스크(`/var/lib/docker`)에 있으므로 그 디스크를 EBS로 둔다.
  - 루트 EBS는 기본값이 「인스턴스 종료 시 삭제」(`DeleteOnTermination=true`)다. 끄거나, Docker 데이터용 EBS를 따로 붙인다.
  - 인스턴스 종료 방지(termination protection)를 켜고, EBS 스냅샷을 정기로 남긴다(위 백업 파일과 별도).
  - 업로드·산출물이 그 디스크에 쌓이므로 디스크 사용량을 지켜본다.
- 볼륨 이름은 compose 프로젝트 이름(`name: specton-deploy`)에 묶인다. `-p`로 다른 이름을 주면 빈 볼륨으로 떠서
  데이터 없이 시작한다. 운영에서는 `-p`를 쓰지 않는다(위 복구 확인은 일부러 다른 이름의 빈 볼륨에 했다).

## 격리 DB (sandbox)

- sandbox 역할은 슈퍼유저·DB 생성·역할 생성 권한이 없고, 앱 DB 접속(CONNECT)이 막혀 있다. 실행 시간 제한 10초. (로컬에서 확인함)
- 외부 네트워크·호스트 파일·확장 설치에 접근할 수 없게 한다.
- SQL 문법만 보고 실행하지 않는다. 지원하는 AST(CREATE/ALTER 등)와 함수·표현식 허용 범위를 정의한다.
- 트랜잭션 제어는 실행기가 소유한다. 입력 DDL의 COMMIT으로 롤백을 우회하지 못하게 한다.
- 생성된 고객 DDL을 플랫폼 초기화 SQL로 쓰지 않는다.
- 검증 실행 (`specton/validate/sandbox.py`, #15, 값은 R4 제안):
  - 허용 SQL 검사(`allowed_sql.py`)를 함수 안에서 다시 통과한 SQL만 실행한다. 앱 DB 연결 풀을 쓰지 않고 전용 연결을 연다.
  - 사전 확인: PostgreSQL 18, 슈퍼유저·DB 생성·역할 생성 권한 없음, 앱 DB 아님·앱 DB 접속 권한 없음. 어긋나면 실행하지 않고 `error`.
  - 검증마다 코드가 만든 스키마(`specton_check_<uuid>`)를 트랜잭션 안에서 만들고 검색 경로를 그 스키마와 `pg_temp`로 고정한다.
  - 시간 제한: 연결 5초, 문장 하나 10초(`statement_timeout`), 잠금 대기 2초(`lock_timeout`), SQL 전체 10초(클라이언트 타이머가 진행 중 문장 취소). 역할의 10초 제한은 바깥 안전장치로 둔다.
  - 성공해도 COMMIT하지 않고, 실패·시간 초과·예외에도 롤백한 뒤 연결을 닫는다. 새 연결로 검증 스키마가 남지 않았는지 확인하고, 남았으면 지우지 않고 `error`로 보고한다.
  - SQL 결함으로 확인된 SQLSTATE만 `failed`, 나머지(연결·권한·시간 초과·잠금·내부 장애)는 `error`. `error`에는 내부 메시지·접속 정보를 넣지 않는다.
  - Windows의 Docker Desktop에서는 `localhost`가 IPv6를 먼저 시도해 연결마다 연결 제한 시간만큼 늦어질 수 있다(로컬 확인: 5초). `127.0.0.1` 주소를 쓰면 피한다.

## 운영 절차

- **시작:** 설정 확인 → DB·역할 준비 → 앱 메타데이터·checkpointer 초기화 → API·실행기 → UI → 샘플 검증
- API의 `create_graph`는 실제 모델 정리와 #15 실패 변환기를 등록한다. 둘 다 `settings.pack_root`를 사용하며, 변환기의 규칙 심각도는 그래프를 만들 때 공통 팩에서 읽는다. 정리 실패는 재작업 또는 사람 확인으로 보내고 생성·LLM 검토를 건너뛴다. 팩 불일치·읽기 실패·출력 추적 오류는 실행 오류로 끝낸다. DDL·ERD·RTM 생성, 후속 규칙 검사와 내보내기는 실제 구현 인계 후 연결한다.
- **중지:** 신규 접수 중단 → 현재 단계 상태 기록 → 작업 lease 정리 → API·실행기 종료
- 강제 종료 후에는 마지막 체크포인트와 부분 파일 상태를 대조한다. LLM 응답을 받고 저장 전에 실패한 구간의 중복 호출·비용을 기록한다.

### 생성 결과 저장 (#17)

- 생성기 어댑터는 `specton.artifacts.write_artifact(storage_dir, design, kind, file_format, content)`로 완성된 바이트를 저장한다. 반환값을 `generated_artifacts: {artifact_key(result["ref"]): result}`로 노드 결과에 넣는다. 실제 DDL·ERD·RTM 생성기의 함수 인터페이스는 각각 인계받아 연결한다.
- 이 내부 인계 정보는 `ArtifactRef`·저장소 상대 경로·생성에 사용한 모델 해시다. 모델 해시는 `save_model`과 같은 계산을 사용하며 파일 해시와 구분한다. 병렬 결과를 revision·종류·형식별로 모아 체크포인트에 남긴다. 규칙 검사와 검토 노드는 현재 revision의 `DesignState.artifacts`를 읽는다.
- 파일 경로는 `<run_id>/r<revision>/<kind>-<sha256>.<file_format>`이며 기존 파일을 덮어쓰지 않는다. 실행기는 파일 존재·내용 해시·현재 모델 일치를 확인한 뒤 진행·모델·산출물 메타데이터·산출물 이벤트를 한 DB 트랜잭션으로 게시한다. 승인본(`approved=True`)은 해당 모델의 실제 승인 기록이 있어야 게시한다. 초안 바이트를 자동으로 승인본으로 바꾸지 않으며, export 어댑터가 승인본을 명시적으로 반환한다.
- 앱 저장 전 중단돼도 체크포인트의 인계 정보로 게시를 복구한다. 파일이 없거나 해시가 다르면 실행을 실패 처리하고 게시하지 않는다. 파일 재생성은 실제 생성기 연결 후의 복구 범위다. DB 커밋 전 중단되거나 취소된 파일은 참조되지 않은 채 남을 수 있으며, 파일 정리·보존 정책(#21)에서 처리한다.

## 장애 대응

| 상황 | 확인 | 대응 |
|---|---|---|
| OpenAI 오류·거절 | 오류 유형·예산·호출 ID | 정책 범위 재시도 또는 failed. 키·본문 노출 금지 |
| 호출 한도(429) | 동시 요청 수 | 재시도 백오프, 동시 실행 수 제한 |
| 추출 실패·빈 결과 | 파일·시트·추출 로그 | 파일 단위 실패는 `EXTRACTION_FAILED`와 안내, 블록 단위 `fail`은 UI-02에서 제외해야 진행. 분석으로 진행 금지 (ADR-0015) |
| DDL 실패·시간 초과 | 파싱/권한/의존/잠금 구분 | 롤백·연결 정리·sandbox 잔여 객체 확인 |
| HITL 재개 충돌 | interrupt·revision·응답 이력 | 409, 최신 상태 조회 후 재검토 |
| 산출물 일부 실패 | 가지별 상태·`model_hash` | 실패 가지만 재생성, 같은 버전만 합류 |
| 저장 공간 부족 | 원문·산출물 크기 | 접수 중단·승인된 정리. 입력을 조용히 지우지 않음 |

## 보안

- 실제 키는 실행 환경에만 주입한다. 저장소·문서·로그에 복사하지 않는다 (`.env`는 커밋 금지, `.env.example`에는 이름만).
- 업로드 본문은 비신뢰 입력이다. 프롬프트 규칙을 바꾸거나 코드·SQL 실행 권한을 주지 않는다.
- 지원 입력(Excel·CSV·HWPX·HWP)의 MIME·확장자·크기·압축 해제 크기를 검사한다. PDF 입력은 범위 밖으로 거절하며, PDF 출력 렌더러는 외부 리소스를 차단한다.
- 실패 로그는 run·stage·error_code·호출 ID 중심. 원문 전문은 기본 제외. 근거 확인에 실패한 지적의 인용문도 로그에 넣지 않고 길이만 남긴다 (#21).
- 업로드 내용 검사 (#21): 확장자 확인 뒤 xlsx·hwpx는 zip 항목을 실제로 풀어 보며 크기를 센다. zip에 적힌 크기는 믿지 않고, 합이 `SPECTON_MAX_UNZIPPED_MB`(기본 200)를 넘는 순간 멈춘다. 구조가 깨졌거나 선언 크기와 실제 크기가 다르면 415다. csv는 NUL 바이트가 없어야 하고, BOM 있는 UTF-16은 해독되면 통과한다. 어긋나면 파일을 지우고 파서에 넘기지 않는다(415·413). 저장 이름은 사용자 파일명을 쓰지 않는다.
- **파싱 원문 수 한도 (#17·#216):** `SPECTON_MAX_SOURCE_BLOCKS`(기본 1,000, 양수 설정)는 파일을 한 번 읽은 뒤 추출된 원문 블록을 실행 전체로 합산해 제한한다. Excel·CSV·HWPX·HWP에 같은 기준이며 `pass`·`review`·원문 없는 블록을 모두 센다. 물리적인 시트 행 수나 A01이 분할한 요구사항 수가 아니다. 한도까지 허용하고 초과하면 A01·LLM 호출 전에 `EXTRACTION_FAILED`로 종료해 설정 상한·실제 건수·문서 분할 안내를 상태 조회와 SSE에 남긴다. 일부 행을 잘라 정상 처리하지 않는다. 업로드의 202 접수 이후 실행 실패이며 HTTP 413으로 소급하지 않는다. 로컬 `.env`와 배포 compose 환경 변수로 조절한다. 1,000은 초기 운영 상한이며 파싱 메모리·문장 길이·LLM 처리량을 보장하는 값이 아니다. 업로드/압축 해제 크기 제한과 실행 토큰 한도(`max_tokens_per_run`, 기본 400,000)는 별도로 유지한다.
- HTTPS로 배포하면 `SPECTON_SESSION_COOKIE_SECURE=true`로 세션 쿠키에 `Secure`를 붙인다(기본 끔, 로컬 HTTP 시연 때문). 쿠키는 항상 `HttpOnly`·`SameSite=Lax`다 (#21, PR #108 리뷰).
- 고객 문서를 외부 LLM으로 보내도 되는지 확인 전까지 **합성·비식별 데이터만** 쓴다 (ADR-0007).
- GitHub 저장소는 비밀값 스캔·push 차단, Dependabot 보안 업데이트를 켜 두었다.

## 자료 수명주기

- 세션은 로컬 단일 세션이고 서버가 발급한 쿠키 값을 `owner_ref`로 쓴다. 업로드 파일은 시연 후 삭제하며, 보존 기간은 시연 계획(#23)에서 정한다 (ADR-0011).
- 삭제는 파일·문서·상태·체크포인트를 함께 처리하고 실패를 기록한다.
- 백업 대상은 플랫폼 DB와 파일 manifest. sandbox는 재생성 가능하게 둔다. 복구 후 원문·산출물 해시를 대조한다. 배포 환경의 명령은 「데이터 보존·백업·복구」를 따른다.

## 릴리스·시연 체크리스트

- [ ] 코드·lock·팩·프롬프트·계약 버전과 릴리스 태그 기록
- [ ] 새 개발 환경과 AWS 환경에서 설치·기동·두 도메인 샘플 재현
- [ ] Excel·CSV·HWPX·HWP 지원 입력, 한글 PDF 출력·HITL·다운로드·실패/재개 시연(PDF 입력은 인수 범위 밖, #10)
- [ ] 실제 평가 결과·미실행·미지원·남은 위험 인수
- [ ] 비밀값·개인 원문·검증용 임시 파일이 배포 패키지에 없는지 확인
- [ ] 배포 검증: 컨테이너 교체·재배포(`up -d --no-build --force-recreate`) 뒤에도 기존 실행·업로드·산출물 내려받기가 유지되는지
- [ ] 배포 검증: 백업 파일로 빈 볼륨에 복구해 같은 실행이 보이는지, EBS 종료 시 보존·종료 방지·스냅샷 설정 확인
