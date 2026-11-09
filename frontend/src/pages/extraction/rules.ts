// UI-02 추출 확인 규칙. 화면(ExtractionPanel)과 분리해 테스트한다.
// 규칙: docs/06-api.md 「사용자 확인 응답」, docs/09 UI-02, ADR-0015, 구현 가이드 강의 10.
// - review 블록: 확인 또는 제외. 제외하면 사유 필수(공백만 있으면 안 됨)
// - fail 블록: 제외만 가능. 사유는 선택. 제외하지 않은 fail이 남으면 보낼 수 없다
// - pass 블록: 결정하지 않는다
// 서버(persistence/runs.py _check_extraction)도 같은 조건을 422로 막는다. 화면은 보내기 전에 알려 준다.
import type { ExtractionResponse } from '../../api/types.ts'
import type { ExtractionBlock, SourceRef } from '../../api/viewItems.ts'

export type Decision = { exclude: boolean; reason: string }
export type Decisions = Record<string, Decision>

const ORDER: Record<ExtractionBlock['extraction_status'], number> = { fail: 0, review: 1, pass: 2 }

/** fail → review → pass 순서. 같은 판정 안에서는 원문 순서를 지킨다. */
export function sortBlocks(blocks: readonly ExtractionBlock[]): ExtractionBlock[] {
  return blocks
    .map((block, index) => ({ block, index }))
    .sort((a, b) => ORDER[a.block.extraction_status] - ORDER[b.block.extraction_status] || a.index - b.index)
    .map(({ block }) => block)
}

/** 확인할 블록(review·fail)만 결정을 둔다. 처음에는 모두 「확인」(제외 안 함). */
export function initialDecisions(blocks: readonly ExtractionBlock[]): Decisions {
  const decisions: Decisions = {}
  for (const b of blocks) {
    if (b.extraction_status !== 'pass') decisions[b.block_id] = { exclude: false, reason: '' }
  }
  return decisions
}

/** 원문 위치 문장 (SourceRef의 형식별 필수 칸, contracts/base.py) */
export function locationText(ref: SourceRef): string {
  switch (ref.file_format) {
    case 'xlsx':
      return `${ref.sheet ?? '?'} 시트 ${ref.row ?? '?'}행`
    case 'csv':
      return `${ref.row ?? '?'}행`
    case 'pdf':
      return `${ref.page ?? '?'}쪽 ${ref.block ?? '?'}번째 블록`
    case 'hwpx': {
      const base = `${ref.section ?? '?'}구역 ${ref.paragraph ?? '?'}문단`
      return ref.table != null ? `${base} · 표 ${ref.table}` : base
    }
  }
}

export const STATUS_LABEL: Record<ExtractionBlock['extraction_status'], string> = {
  fail: '실패',
  review: '확인 필요',
  pass: '정상',
}

/** 보내기 전에 막는 문제. 메시지는 서버 422처럼 블록 ID로 시작한다. */
export function problems(blocks: readonly ExtractionBlock[], decisions: Decisions): string[] {
  const found: string[] = []
  for (const b of blocks) {
    const d = decisions[b.block_id]
    if (b.extraction_status === 'fail' && !d?.exclude) {
      found.push(`${b.block_id}: 추출에 실패한 블록은 제외해야 합니다`)
    }
    if (b.extraction_status === 'review' && d?.exclude && !d.reason.trim()) {
      found.push(`${b.block_id}: 제외 사유를 적어 주세요`)
    }
  }
  return found
}

/** 확인 답 (confirmed: true). 제외한 블록만 담는다. 목록에 없는 review 블록은 서버가 「확인」으로 둔다. */
export function buildResponse(blocks: readonly ExtractionBlock[], decisions: Decisions): ExtractionResponse {
  return {
    kind: 'extraction',
    confirmed: true,
    excluded_blocks: blocks
      .filter((b) => b.extraction_status !== 'pass' && decisions[b.block_id]?.exclude)
      .map((b) => ({ block_id: b.block_id, reason: decisions[b.block_id].reason.trim() || null })),
  }
}

/** 전체 중단 답. 실행이 cancelled가 된다. */
export const STOP_RESPONSE: ExtractionResponse = { kind: 'extraction', confirmed: false, excluded_blocks: [] }

export type RelatedWarning = { block_id: string; source_id: string; related_block_ids: string[] }

/**
 * 제외하려는 원문의 ID가 남는 원문의 「관련 요구사항」에 나오는지 (docs/09 UI-02, ADR-0015 결정 5).
 * 막지 않고 안내만 한다. 서버(graph.py _related_warnings)와 같은 기준:
 * ID 앞뒤가 다른 글자·숫자·`-`가 아닐 때만 같은 ID로 본다 (「SFR-0031」 ≠ 「SFR-003」).
 */
export function relatedWarnings(blocks: readonly ExtractionBlock[], decisions: Decisions): RelatedWarning[] {
  const excluded = (b: ExtractionBlock) => b.extraction_status !== 'pass' && decisions[b.block_id]?.exclude === true
  const remaining = blocks.filter((b) => !excluded(b) && b.source_related_requirements)
  const warnings: RelatedWarning[] = []
  for (const block of blocks) {
    if (!excluded(block) || !block.source_id) continue
    const id = block.source_id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const sameId = new RegExp(`(?<![\\p{L}\\p{N}_-])${id}(?![\\p{L}\\p{N}_-])`, 'u')
    const related = remaining.filter((r) => sameId.test(r.source_related_requirements ?? '')).map((r) => r.block_id)
    if (related.length > 0) warnings.push({ block_id: block.block_id, source_id: block.source_id, related_block_ids: related })
  }
  return warnings
}

/** 건너뛴 시트 안내 (SSE status 이벤트 payload.info = "skipped_sheets") */
export function skippedSheets(payloads: readonly (Record<string, unknown> | undefined)[]): string[] {
  const sheets: string[] = []
  for (const p of payloads) {
    if (p?.info === 'skipped_sheets' && Array.isArray(p.sheets)) {
      for (const s of p.sheets) if (typeof s === 'string' && !sheets.includes(s)) sheets.push(s)
    }
  }
  return sheets
}
