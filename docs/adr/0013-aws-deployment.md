# ADR-0013: AWS 배포

- 날짜: 2026-10-23
- 상태: 제안
- 결정자: 팀 설계로 (회의에서 승인·수정·보류)

## 배경

AWS에 Docker 컨테이너로 배포하기로 했다. 시연 목적이며 운영 SLA는 없다. App Runner는 2026-04-30부터 신규 고객을 받지 않는다.

## 결정

- EC2 또는 Lightsail 1대에 Docker Compose로 배포한다. 로컬과 같은 이미지를 쓴다.
- 접근은 IP 제한·HTTPS. 키는 환경 변수로 주입하고 예산 알림을 설정한다.
- 배포 전 compose의 DB 기본 비밀번호를 없애고 환경 변수를 필수로 받는다.

## 검토한 대안

| 대안 | 장점 | 단점 | 기각 이유 |
|---|---|---|---|
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
- 감수할 점: 서버 1대라 장애 시 시연이 멈춘다. 로컬 시연을 대체 경로로 유지한다.
- 관련 문서: [11 배포·운영·보안](../11-deployment-security.md)
