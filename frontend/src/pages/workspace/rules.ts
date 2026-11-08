// UI-05 결과 작업공간·UI-07 다운로드의 규칙. 화면 코드와 분리해 테스트한다.
// 산출물 종류·형식은 docs/06 「산출물 형식」, 화면 흐름은 docs/09를 따른다.
import { ApiError } from '../../api/errors.ts'
import type { RunState } from '../../api/types.ts'
import type { ArtifactRef } from '../../api/viewItems.ts'

export type ArtifactKind = ArtifactRef['kind']
export type ArtifactFormat = ArtifactRef['file_format']

/** 종류마다 받을 수 있는 형식 (docs/06). 다른 조합은 서버가 422로 거절한다. */
export const ARTIFACT_FORMATS: Record<ArtifactKind, readonly ArtifactFormat[]> = {
  functions: ['md', 'pdf'],
  erd: ['mmd', 'pdf'],
  ddl: ['sql'],
  rtm: ['xlsx', 'csv'],
  requirements: ['md'],
  review: ['md'],
}

/** 화면에 보일 순서와 이름 */
export const KIND_LABEL: Record<ArtifactKind, string> = {
  functions: '기능 명세',
  erd: 'ERD',
  ddl: 'DDL (SQL)',
  rtm: 'RTM (추적표)',
  requirements: '요구사항',
  review: '검토 결과',
}

export const KIND_ORDER: readonly ArtifactKind[] = ['functions', 'erd', 'ddl', 'rtm', 'requirements', 'review']

export const FORMAT_LABEL: Record<ArtifactFormat, string> = {
  md: 'Markdown',
  pdf: 'PDF',
  mmd: 'Mermaid',
  sql: 'SQL',
  xlsx: 'Excel',
  csv: 'CSV',
}

/** 설계 뒤 병렬로 만드는 산출물 (specton/graph.py GENERATORS). 없으면 그 가지가 미완성이다. */
export const GENERATED_KINDS: readonly ArtifactKind[] = ['erd', 'ddl', 'rtm']

/** view의 artifacts(자유 형식 객체)에서 모양이 맞는 것만 고른다. 모르는 종류·형식은 버린다. */
export function toArtifacts(raw: readonly unknown[] | undefined): ArtifactRef[] {
  return (raw ?? []).filter((a): a is ArtifactRef => {
    if (typeof a !== 'object' || a === null) return false
    const { kind, file_format, revision } = a as Partial<ArtifactRef>
    return (
      typeof kind === 'string' &&
      kind in ARTIFACT_FORMATS &&
      typeof file_format === 'string' &&
      ARTIFACT_FORMATS[kind].includes(file_format) &&
      typeof revision === 'number'
    )
  })
}

/** 아직 만들어지지 않은 생성 가지 (UI-05 「미완성 가지는 미완성으로 표시」) */
export function missingKinds(artifacts: readonly ArtifactRef[]): ArtifactKind[] {
  const made = new Set(artifacts.map((a) => a.kind))
  return GENERATED_KINDS.filter((k) => !made.has(k))
}

/** 이 revision의 파일이 모두 승인본인지. 하나라도 초안이면 초안으로 본다. */
export function isApproved(artifacts: readonly ArtifactRef[]): boolean {
  return artifacts.length > 0 && artifacts.every((a) => a.approved)
}

/** 다운로드 칸 하나의 상태 */
export type FileState =
  | { state: 'ready'; artifact: ArtifactRef }
  | { state: 'needs-approval' } // PDF는 승인한 revision에서만 만든다
  | { state: 'not-ready' } // 아직 만들지 않음 (생성 대기·실패한 가지)

export type DownloadRow = {
  kind: ArtifactKind
  files: { format: ArtifactFormat; file: FileState }[]
}

/** UI-07 표: 종류마다 형식별 상태. 목록에 없는 PDF는 승인 전이면 「승인 후」로 구분한다. */
export function downloadRows(artifacts: readonly ArtifactRef[], approved: boolean): DownloadRow[] {
  return KIND_ORDER.map((kind) => ({
    kind,
    files: ARTIFACT_FORMATS[kind].map((format) => {
      const artifact = artifacts.find((a) => a.kind === kind && a.file_format === format)
      const file: FileState = artifact
        ? { state: 'ready', artifact }
        : format === 'pdf' && !approved
          ? { state: 'needs-approval' }
          : { state: 'not-ready' }
      return { format, file }
    }),
  }))
}

/** 화면에 보일 파일 이름. 서버와 같은 규칙: specton-<kind>-r<revision>[-draft].<format> (docs/06) */
export function fileNameOf(a: Pick<ArtifactRef, 'kind' | 'file_format' | 'revision' | 'approved'>): string {
  return `specton-${a.kind}-r${a.revision}${a.approved ? '' : '-draft'}.${a.file_format}`
}

/** 내려받기 실패 안내 (UI-07 「생성 대기·파일 없음·접근 불가 안내」). 서버 문구가 있으면 먼저 쓴다. */
export function downloadErrorText(err: unknown): string {
  if (!(err instanceof ApiError)) return '파일을 받지 못했습니다.'
  if (err.body?.message) return err.body.message
  switch (err.code) {
    case 'ARTIFACT_NOT_READY':
      return '파일이 아직 만들어지지 않았습니다. PDF는 승인한 뒤에 만들어집니다.'
    case 'ARTIFACT_FORMAT_UNSUPPORTED':
      return '이 산출물은 그 형식으로 받을 수 없습니다.'
    case 'RUN_NOT_FOUND':
      return '실행을 찾을 수 없거나 접근할 수 없습니다.'
    case 'NETWORK':
      return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
    default:
      return `파일을 받지 못했습니다 (HTTP ${err.status}).`
  }
}

// ── ERD 보기 ──────────────────────────────────────────────

/** mermaid가 만든 SVG의 원래 크기(viewBox). 확대·축소의 기준이다. */
export function svgSize(svg: string): { width: number; height: number } | null {
  const box = /viewBox="([\d.\s-]+)"/.exec(svg)
  if (!box) return null
  const [, , width, height] = box[1].trim().split(/\s+/).map(Number)
  return width > 0 && height > 0 ? { width, height } : null
}

/** 확대 단계. 너무 작거나 크게는 가지 않는다. */
const ZOOM_LEVELS = [0.25, 0.33, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2]

export const zoomSteps = {
  next: (scale: number) => ZOOM_LEVELS.find((z) => z > scale + 0.001) ?? ZOOM_LEVELS[ZOOM_LEVELS.length - 1],
  prev: (scale: number) => [...ZOOM_LEVELS].reverse().find((z) => z < scale - 0.001) ?? ZOOM_LEVELS[0],
}

/** revision 고르기 목록. 최신이 먼저. */
export function revisionOptions(current: number): number[] {
  return Array.from({ length: current + 1 }, (_, i) => current - i)
}

// ── 화면 전환 (주소의 &view=) ─────────────────────────────

/** 결과가 있는 상태에서 고를 수 있는 화면. 첫 번째가 기본 화면이다. */
export type ResultView = 'review' | 'workspace' | 'downloads'

export function resultViews(status: RunState): ResultView[] {
  if (status === 'awaiting_review') return ['review', 'workspace']
  if (status === 'completed') return ['downloads', 'workspace']
  return []
}

/** 주소의 view 값을 지금 상태에서 고를 수 있는 화면으로 바꾼다. 맞지 않으면 기본 화면. */
export function chosenView(status: RunState, param: string | null): ResultView | null {
  const views = resultViews(status)
  if (views.length === 0) return null
  return views.includes(param as ResultView) ? (param as ResultView) : views[0]
}

export const VIEW_LABEL: Record<ResultView, string> = {
  review: '최종 검토',
  workspace: '결과 작업공간',
  downloads: '다운로드',
}

// ── 이전 실행 (UI-07 이력) ────────────────────────────────

export const STATUS_LABEL: Record<RunState, string> = {
  queued: '대기',
  parsing: '문서 읽는 중',
  awaiting_input: '추출 확인 대기',
  analysing: '분석 중',
  awaiting_requirements: '분석 확인 대기',
  designing: '설계 중',
  generating: '산출물 생성 중',
  reviewing: '검토 중',
  awaiting_review: '최종 검토 대기',
  exporting: '내보내는 중',
  completed: '완료',
  failed: '실패',
  cancel_requested: '취소 요청',
  cancelled: '취소됨',
}

/** 실행 시각을 짧게 (예: 11/8 15:32). 날짜를 못 읽으면 원문 그대로. */
export function shortTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
