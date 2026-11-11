// 서버 RTM CSV를 그대로 미리 본다. 연결·제외·비고를 재계산하지 않는다.
export const RTM_COLUMNS = ['원문 ID', '원문 위치', '요구사항 ID', '상위 요구사항', '요구사항', '유형', '기능', '엔티티', '관계', '상태', '비고'] as const
export type RtmRow = Record<(typeof RTM_COLUMNS)[number], string>

export class RtmFormatError extends Error {}

/** BOM과 RFC 4180 인용 필드(쉼표·개행·이중 따옴표)를 보존한다. */
export function parseRtmCsv(text: string): RtmRow[] {
  const rows: string[][] = []
  let row: string[] = [], field = '', quoted = false
  const source = text.replace(/^\uFEFF/, '')
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (ch === '"') {
      if (quoted && source[i + 1] === '"') { field += '"'; i++ }
      else if (quoted || field === '') quoted = !quoted
      else throw new RtmFormatError('RTM CSV 인용 형식이 올바르지 않습니다.')
    } else if (!quoted && ch === ',') { row.push(field); field = '' }
    else if (!quoted && (ch === '\r' || ch === '\n')) {
      if (ch === '\r' && source[i + 1] === '\n') i++
      row.push(field); rows.push(row); row = []; field = ''
    } else field += ch
  }
  if (quoted) throw new RtmFormatError('RTM CSV 인용이 닫히지 않았습니다.')
  if (field || row.length) { row.push(field); rows.push(row) }
  const header = rows.shift()
  if (!header || header.length !== RTM_COLUMNS.length || RTM_COLUMNS.some((name, i) => header[i] !== name)) {
    throw new RtmFormatError('RTM CSV 열이 서버 계약과 다릅니다.')
  }
  return rows.map((values) => {
    if (values.length !== RTM_COLUMNS.length) throw new RtmFormatError('RTM CSV 행의 열 수가 올바르지 않습니다.')
    return Object.fromEntries(RTM_COLUMNS.map((name, i) => [name, values[i]])) as RtmRow
  })
}
