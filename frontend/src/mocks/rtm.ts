import type { AnalysedRequirement, DesignItem, ExtractionBlock } from '../api/viewItems.ts'
import { RTM_COLUMNS } from '../pages/workspace/rtm.ts'

// 목업도 정식 RTM의 11열·직접 req_ids 조인·제외 행을 사용한다.
export function mockRtmCsv(requirements: readonly AnalysedRequirement[], design: readonly DesignItem[], sources: readonly ExtractionBlock[]): string {
  const rows: string[][] = requirements.map((req) => {
    const ids = (type: DesignItem['type']) => design.filter((d) => d.type === type && d.req_ids.includes(req.id)).map((d) => d.id).join('; ')
    const functions = ids('function')
    return [req.source_id ?? '', JSON.stringify(req.source_ref), req.id, req.parent_id ?? '', req.text, req.type,
      functions, ids('entity'), ids('relationship'), functions ? '연결' : '미연결', req.quality_issues.map((q) => q.message).join('; ')]
  })
  for (const source of sources) {
    if (source.user_decision === 'excluded' || !source.source_text) {
      rows.push([source.source_id ?? '', JSON.stringify(source.source_ref), '', '', source.source_text ?? '', '', '', '', '',
        source.user_decision === 'excluded' ? '제외' : '확인(원문 없음)', source.excluded_reason ?? source.notice ?? ''])
    }
  }
  const cell = (s: string) => `"${s.replace(/"/g, '""')}"`
  return '\uFEFF' + [RTM_COLUMNS, ...rows].map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n'
}
