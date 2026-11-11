// UI-01 업로드 규칙. 화면(UploadPage)과 분리해 테스트한다.
// - 브라우저에서 미리 검사해 바로 알려 주는 용도다. 최종 판단은 서버가 한다(docs/06-api.md POST /runs).
// - 형식·크기·빈 파일 문구는 서버(specton/api/uploads.py·runs.py)·mock과 같게 둔다.
import { ApiError, errorMessage } from '../../api/errors.ts'
import type { Pack } from '../../api/types.ts'

/** 서버 기본 한도(specton/config.py max_upload_mb). 서버 설정을 바꾸면 여기도 맞춘다. */
export const MAX_UPLOAD_MB = 20

/**
 * 화면에서 받는 형식 (구현 가이드 강의 10). 서버 ACCEPTED_FORMATS와 같은 순서다.
 * 한글(.hwpx·.hwp)은 요구사항 상세표를 읽는다(#24).
 */
export const ACCEPTED_FORMATS = ['xlsx', 'csv', 'hwpx', 'hwp'] as const

/** 파일 고르기 창에서 보일 확장자 */
export const ACCEPT_ATTR = ACCEPTED_FORMATS.map((f) => `.${f}`).join(',')

/** 화면 안내에 쓰는 형식 목록 (예: .xlsx · .csv · .hwpx · .hwp) */
export const FORMATS_LABEL = ACCEPTED_FORMATS.map((f) => `.${f}`).join(' · ')

/**
 * 팩 이름과 화면 표시. Record<Pack, …>라서 계약(openapi.json)에 팩이 늘면 여기서 타입 오류가 난다.
 * 설명은 domain_packs/<팩>/manifest.yaml의 description을 한글로 줄였다.
 */
export const PACK_LABELS: Record<Pack, { label: string; description: string }> = {
  inventory: { label: '재고관리', description: '부품·소모품 기준정보와 입고·출고·반품·조정·이동' },
  maintenance: { label: '설비보전', description: '설비 대장, 예방보전, 고장 접수, 작업 지시·결과' },
}

/** 화면에서 고를 수 있는 팩. 지금은 재고관리만 설계한다. 설비보전을 열 때 여기에 'maintenance'를 넣는다. */
export const ENABLED_PACKS: readonly Pack[] = ['inventory']

export const PACK_OPTIONS = ENABLED_PACKS.map((value) => ({
  value,
  label: PACK_LABELS[value].label,
}))

function suffixOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase()
}

/** 고른 파일을 미리 검사한다. 문제가 없으면 null, 있으면 파일 칸에 보일 문장. */
export function checkFile(file: Pick<File, 'name' | 'size'>): string | null {
  const suffix = suffixOf(file.name)
  if (!(ACCEPTED_FORMATS as readonly string[]).includes(suffix)) {
    return `지원하는 형식은 ${ACCEPTED_FORMATS.map((f) => `.${f}`).join(', ')}입니다.`
  }
  if (file.size === 0) return '빈 파일입니다.'
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `파일이 ${MAX_UPLOAD_MB}MB를 넘습니다.`
  return null
}

/** 오류를 보일 자리. 파일·팩 오류는 해당 칸 아래에, 나머지는 버튼 위 안내에 보인다 (docs/09 UI-01). */
export type ErrorPlace = 'file' | 'pack' | 'form'

export function errorPlace(err: unknown): ErrorPlace {
  if (!(err instanceof ApiError)) return 'form'
  switch (err.code) {
    case 'UPLOAD_TOO_LARGE':
    case 'UNSUPPORTED_MEDIA_TYPE':
    case 'EXTRACTION_FAILED':
      return 'file'
    case 'PACK_UNSUPPORTED':
      return 'pack'
    default:
      return 'form'
  }
}

/** 서버 오류를 자리와 문장으로 바꾼다. */
export function placeError(err: unknown): { place: ErrorPlace; message: string } {
  return { place: errorPlace(err), message: errorMessage(err) }
}
