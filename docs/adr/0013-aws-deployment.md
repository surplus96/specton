# ADR-0013: AWS 배포

- 날짜: 2026-10-23 (승인 2026-11-09)
- 상태: 승인
- 결정자: R1 (2026-11-09, #25). 제안(2026-10-23)의 방향을 유지하고 서버 종류·접근 규칙을 정했다

## 배경

AWS에 Docker 컨테이너로 배포하기로 했다. 시연 목적이며 운영 SLA는 없다. App Runner는 2026-04-30부터 신규 고객을 받지 않는다.

## 결정

- **서버:** EC2 1대에 Docker Compose(`compose.deploy.yml`)로 배포한다. 로컬과 같은 이미지(#226)를 쓴다. 리전은 서울(`ap-northeast-2`).
  - Lightsail이 아니라 EC2인 이유: 데이터 보존 절차(EBS 종료 시 보존·종료 방지·스냅샷, docs/11 「데이터 보존·백업·복구」, #244)가 EC2 기준이고, 보안 그룹으로 포트마다 허용 IP를 따로 둘 수 있다.
  - 인스턴스 크기: 실행 이미지가 크고(2.28GB, ADR-0004) Chromium·WeasyPrint·PostgreSQL이 함께 돌아 메모리 여유를 둔다. 크기와 CPU 종류(x86_64·arm64)는 기동 때 실측해 #25에 적고, 이미지는 그 CPU에 맞춰 빌드한다(docs/11 「배포 절차 주의」).
- **접근 (보안 그룹):**
  - 80번: 전체 공개. Caddy가 HTTPS 인증서 발급(Let's Encrypt HTTP-01)과 HTTPS로 넘기기에만 쓴다. 80번까지 IP로 막으면 인증서를 받지 못한다.
  - 443번(화면·API): 팀과 시연 장소 IP만 허용한다. 로그인이 없어(ADR-0011) 이 허용 목록이 접근 통제다.
  - 22번(SSH): 팀 IP만 허용하거나 닫고 SSM으로 접속한다.
  - HTTPS에는 도메인이 하나 필요하다(`SPECTON_SITE_ADDRESS`). 세션 쿠키는 `Secure`(`SPECTON_SESSION_COOKIE_SECURE=true`).
- **비밀값:** 키·비밀번호는 `.env.deploy`(커밋 금지)로만 주입하고, compose는 기본값 없이 필수로 받는다(#228).
- **비용:** AWS Budgets로 월 예산 알림을 둔다. OpenAI 사용 한도는 따로 둔다. 금액·받는 사람·AWS 계정과 키 관리자, 이미지 레지스트리(비공개)는 기동 때 정해 #25에 적는다.
- **저장:** 업로드·산출물·DB는 Docker named volume에 둔다(R1 결정, #25). 백업·복구는 docs/11.
- **시연 뒤:** 업로드 삭제·보존 기간은 ADR-0011과 시연 계획(#23)을 따르고, 백업 사본도 같은 대상이다(docs/11).

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
| Lightsail 인스턴스 | 월 고정 요금이라 비용 예측이 쉽다. 인스턴스에서는 compose를 그대로 쓸 수 있다 | 보존 절차(#244)가 EC2 기준, 포트별 IP 규칙이 EC2 보안 그룹보다 단순 | EC2로 결정 (2026-11-09) |
| ECS Fargate | 관리형·확장성 | ECR·IAM 설정 부담 | 기간 대비 과함 |
| App Runner | 간단한 배포 | 신규 고객 미수용 | 사용 불가 |

## 검토 근거

조사일 2026-10-23. 공개 자료 기준이다.

| 후보 | 메모 |
|---|---|
| EC2 1대 + Docker Compose | 로컬 compose를 그대로 사용. 가장 단순 |
| Lightsail | 월 고정 요금이라 비용 예측이 쉬움. Compose 지원 여부는 문서 확인 필요 |
| ECS Fargate (Express Mode) | 관리형·확장성. ECR 이미지 빌드·IAM 설정 부담 |
| App Runner | 2026-04-30부터 신규 고객 미수용 → 제외 |

출처: [App Runner 종료](https://encore.dev/articles/end-of-app-runner) · [App Runner 대안 2026](https://encore.dev/articles/app-runner-alternatives-2026)

## 결과

- 좋아지는 점: 로컬 compose를 거의 그대로 쓴다.
- 감수할 점: 서버 1대라 장애 시 시연이 멈춘다. 로컬 시연을 대체 경로로 유지한다. 80번이 전체 공개라 HTTP 요청은 받지만 HTTPS로 넘기기만 하고 화면·API는 443번 허용 IP에서만 열린다.
- 관련 문서: [11 배포·운영·보안](../11-deployment-security.md)
