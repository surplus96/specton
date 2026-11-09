// 화면 코드에서 쓰기 쉬운 이름으로 API 타입을 다시 내보낸다.
// 원본은 schema.d.ts이고, 이 파일은 docs/api/openapi.json에서 자동 생성한다(`npm run gen:api`).
// 계약이 바뀌면 schema.d.ts를 다시 생성할 뿐, 여기서 필드를 손으로 적지 않는다.
import type { components, operations } from './schema'

type Schemas = components['schemas']

export type RunStatus = Schemas['RunStatus']
export type RunState = RunStatus['status']
export type RunSummary = Schemas['RunSummary']
export type RunView = Schemas['RunView']
export type ViewSection = RunView['section']
export type Interrupt = Schemas['Interrupt']
export type InterruptKind = Interrupt['kind']
export type ApiErrorBody = Schemas['Error']
export type ErrorCode = Schemas['ErrorCode']

export type ResumeRequest = Schemas['ResumeRequest']
export type ExtractionResponse = Schemas['ExtractionResponse']
export type RequirementsResponse = Schemas['RequirementsResponse']
export type ReviewResponse = Schemas['ReviewResponse']

export type SseEvent = Schemas['SseEvent']
export type SseEventName = SseEvent['event']
export type SseEventData = Schemas['SseEventData']

export type Pack =
  operations['createRun']['requestBody']['content']['multipart/form-data']['pack']

type ArtifactParams = operations['downloadArtifact']['parameters']
export type ArtifactKind = ArtifactParams['path']['kind']
export type FileFormat = ArtifactParams['query']['file_format']
