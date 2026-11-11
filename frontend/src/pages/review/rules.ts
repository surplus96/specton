// UI-06 최종 검토 규칙. 화면(ReviewPanel)과 분리해 테스트한다.
// 규칙: docs/06-api.md 「사용자 확인 응답」·「SSE」, docs/09 UI-06, ADR-0010, 구현 가이드 강의 07·10.
// - 승인: decision 'approve', feedback ''(필수 칸). critical 지적이 남아 있으면 승인할 수 없다
//   (서버도 422 「차단 오류가 남아 있어 승인할 수 없습니다.」로 막는다)
// - 수정 요청: decision 'revise', feedback에 요청 문장
// - 보류: decision 'hold'. 같은 확인 요청으로 계속 기다린다
import type { ReviewResponse, SseEvent } from '../../api/types.ts'
import type { DesignItem, Finding, Severity } from '../../api/viewItems.ts'
import { revisionText } from '../runMeta.ts'

export const SEVERITY_LABEL: Record<Severity, string> = { critical: '차단', major: '주요', minor: '참고' }

const SEVERITY_ORDER: Record<Severity, number> = { critical: 0, major: 1, minor: 2 }

/** 차단 → 주요 → 참고 순서, 같은 심각도 안에서는 받은 순서 */
export function sortFindings(findings: readonly Finding[]): Finding[] {
  return findings
    .map((finding, index) => ({ finding, index }))
    .sort((a, b) => SEVERITY_ORDER[a.finding.severity] - SEVERITY_ORDER[b.finding.severity] || a.index - b.index)
    .map(({ finding }) => finding)
}

export function countBySeverity(findings: readonly Finding[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { critical: 0, major: 0, minor: 0 }
  for (const f of findings) counts[f.severity] += 1
  return counts
}

export type SeverityGroup = { severity: Severity; count: number; sample: string }

/**
 * 「검토가 필요한 항목」 요약: 심각도마다 건수와 대표 대상(첫 지적의 첫 대상 이름, 나머지는 「외 n개」).
 * 지적이 없는 심각도는 뺀다. 차단 → 주요 → 참고 순서.
 */
export function severityGroups(findings: readonly Finding[], names: Map<string, string>): SeverityGroup[] {
  const groups: SeverityGroup[] = []
  for (const severity of ['critical', 'major', 'minor'] as const) {
    const mine = findings.filter((f) => f.severity === severity)
    if (mine.length === 0) continue
    const targets = mine.flatMap((f) => f.targets.map((t) => names.get(t.id) ?? t.id))
    const unique = [...new Set(targets)]
    const sample = unique.length === 0 ? '대상 없음' : unique.length === 1 ? unique[0] : `${unique[0]} 외 ${unique.length - 1}개`
    groups.push({ severity, count: mine.length, sample })
  }
  return groups
}

/** 승인 가능 여부 (ADR-0010: 차단 오류가 남아 있으면 승인 불가) */
export function canApprove(findings: readonly Finding[]): boolean {
  return !findings.some((f) => f.severity === 'critical')
}

/** 검토 관점 이름 (docs/04-agents.md 「검토 관점 A05~A08」) */
export const REVIEWER_LABEL: Record<string, string> = {
  A05: '관계 모순',
  A06: '데이터 누락',
  A07: '품질 요구',
  A08: '중복 정리',
}

/** 규칙 코드의 쉬운 이름 (docs/05 규칙 표). 코드 자체는 화면에 쓰지 않고 마우스를 올리면 보인다 */
const RULE_NAME: Record<string, string> = {
  'RULE-01': '참조 확인',
  'RULE-02': '요구사항 연결',
  'RULE-03': '키·데이터 종류',
  'RULE-04': '테이블 연결',
  'RULE-05': '이름 규칙',
  'RULE-06': '만들기·조회·수정·삭제',
  'RULE-07': 'SQL 실행',
}

/** 규칙 코드를 쉬운 이름으로. 공통표준 검사(SC-xx)는 「공통표준 이름」 */
export function ruleName(code: string | null | undefined): string | null {
  if (!code) return null
  if (RULE_NAME[code]) return RULE_NAME[code]
  return code.startsWith('SC-') ? '공통표준 이름' : null
}

/** 의견 출처 문장: 규칙 검사는 쉬운 규칙 이름, AI 의견은 검토 관점 */
export function sourceText(f: Pick<Finding, 'source' | 'rule_code' | 'reviewer_id'>): string {
  if (f.source === 'rule') {
    const name = ruleName(f.rule_code)
    return name ? `규칙 검사 · ${name}` : '규칙 검사'
  }
  const id = f.reviewer_id ?? ''
  return REVIEWER_LABEL[id] ? `${REVIEWER_LABEL[id]} 검토` : `${id} 검토`.trim()
}

export const STAGE_LABEL: Record<NonNullable<Finding['target_stage']>, string> = {
  requirements: '요구사항 분석',
  functions: '기능 설계',
  data_model: '데이터 모델',
}

/** 설계 객체 ID → 화면 이름. 속성은 「엔티티.속성」, 관계는 「부모 → 자식」 */
export function nameIndex(design: readonly DesignItem[]): Map<string, string> {
  const names = new Map<string, string>()
  for (const item of design) {
    if (item.type === 'function') names.set(item.id, item.name)
    if (item.type === 'entity') {
      names.set(item.id, item.name)
      for (const a of item.attributes) names.set(a.id, `${item.name}.${a.name}`)
    }
  }
  for (const item of design) {
    if (item.type === 'relationship') {
      names.set(item.id, `${names.get(item.parent) ?? item.parent} → ${names.get(item.child) ?? item.child}`)
    }
  }
  return names
}

export function targetText(target: Finding['targets'][number], names: Map<string, string>): string {
  const name = names.get(target.id)
  return name ? `${name} (${target.id})` : target.id
}

/** 자동 재작업을 멈추고 사람에게 넘긴 이유 (review/rework.py HitlReason) */
export const HITL_REASON_TEXT: Record<string, string> = {
  rework_limit: '자동 재작업 횟수 한도에 닿아 사람 확인으로 넘어왔습니다.',
  repeated_findings: '같은 지적이 다시 나와 자동 재작업을 멈췄습니다.',
  router_undecided: '어느 단계로 돌아갈지 정하지 못해 사람 확인으로 넘어왔습니다.',
}

/**
 * 최종 검토 안내. 지금 확인 요청(interrupt_id)의 SSE interrupt 이벤트 payload에서 읽는다 (docs/06 「SSE」).
 * - failedBranches: 실패하거나 빠진 검토 관점. 비어 있지 않으면 불완전 검토 (TC-F14)
 * - hitlReason: 자동 루프를 멈춘 이유 (있을 때)
 */
export function reviewNotices(
  events: readonly SseEvent[],
  interruptId: string | null | undefined,
): { failedBranches: string[]; hitlReason: string | null } {
  const event = [...events]
    .reverse()
    .find((e) => e.event === 'interrupt' && e.data.payload?.kind === 'review' && (!interruptId || e.data.payload?.interrupt_id === interruptId))
  const payload = event?.data.payload ?? {}
  const failed = Array.isArray(payload.failed_branches) ? payload.failed_branches.filter((b): b is string => typeof b === 'string') : []
  const reason = typeof payload.hitl_reason === 'string' ? payload.hitl_reason : null
  return { failedBranches: failed, hitlReason: reason }
}

export function branchText(branch: string): string {
  return REVIEWER_LABEL[branch] ?? branch
}

export type Decision = ReviewResponse['decision']

/** 보내기 전에 막는 문제 */
export function problems(decision: Decision, feedback: string, findings: readonly Finding[]): string[] {
  if (decision === 'approve' && !canApprove(findings)) return ['차단 오류가 남아 있어 승인할 수 없습니다. 수정 요청으로 고쳐 주세요.']
  if (decision === 'revise' && !feedback.trim()) return ['수정 요청 내용을 적어 주세요.']
  return []
}

/** 보낼 답. 승인은 feedback을 비워 보낸다(필수 칸이라 빼지 않는다, 강의 07). */
export function buildResponse(decision: Decision, feedback: string): ReviewResponse {
  return { kind: 'review', decision, feedback: decision === 'approve' ? '' : feedback.trim() }
}

/** 현재 확인 요청의 진단만 표시한다. 이전 interrupt의 제외·라우터 결과를 섞지 않는다. */
export function reviewDiagnostics(events: readonly SseEvent[], interruptId: string | null | undefined): string[] {
  if (!interruptId) return []
  const payload = [...events].reverse().find(e => e.event === 'interrupt' && e.data.payload?.kind === 'review' && e.data.payload?.interrupt_id === interruptId)?.data.payload
  if (!payload) return []
  const messages: string[] = []
  if (Array.isArray(payload.rejected_findings)) {
    const rejected = payload.rejected_findings.filter((value) => {
      if (!value || typeof value !== 'object') return false
      const r = value as Record<string, unknown>
      return typeof r.finding_id === 'string' && typeof r.reason === 'string'
    })
    if (rejected.length > 0) messages.push(`근거가 확인되지 않은 의견 ${rejected.length}건은 뺐어요.`)
  }
  const value = payload.router_decision
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const r = value as Record<string, unknown>
    const stages: Record<string, string> = { requirements: '요구사항', functions: '기능 설계', data_model: '데이터 모델' }
    if (typeof r.revision === 'number') {
      const stage = typeof r.stage === 'string' ? stages[r.stage] ?? '판단 불가' : '판단 불가'
      messages.push(`다시 설계할 곳: ${stage} (${revisionText(r.revision)} 기준).${typeof r.rationale === 'string' ? ` ${r.rationale}` : ''}`)
    }
  }
  return messages
}
