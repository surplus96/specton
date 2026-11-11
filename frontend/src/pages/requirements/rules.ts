// UI-03 분석 확인 규칙. 화면(RequirementsPanel)과 분리해 테스트한다.
// 규칙: docs/06-api.md 「사용자 확인 응답」, docs/09 UI-03, 구현 가이드 강의 10.
// - keep: 그대로 (texts 비움) / edit: 문장 1개로 바꿈 / split: 문장 2개 이상으로 나눔
// - 답하지 않은 요구사항은 keep으로 본다
// 서버(contracts/api.py RequirementsResponse.answers_for, #136)도 같은 조건을 422로 막는다.
import type { RequirementsResponse } from '../../api/types.ts'
import type { AnalysedRequirement, NfrCategory } from '../../api/viewItems.ts'

export type Action = 'keep' | 'edit' | 'split'
export type Answer = { action: Action; texts: string[] }
export type Answers = Record<string, Answer>

export const ACTION_LABEL: Record<Action, string> = { keep: '유지', edit: '수정', split: '분할' }

export const NFR_LABEL: Record<NfrCategory, string> = {
  security: '보안',
  audit: '감사',
  retention: '보관',
  performance: '성능',
  availability: '가용성',
  usability: '사용성',
  other: '기타',
}

export function typeText(req: Pick<AnalysedRequirement, 'type' | 'nfr_category'>): string {
  if (req.type === 'FR') return '기능 (FR)'
  return req.nfr_category ? `비기능 · ${NFR_LABEL[req.nfr_category]} (NFR)` : '비기능 (NFR)'
}

/** 같은 원문에서 2건 이상 나온 요구사항 (docs/09 UI-03 「분할」). 원문 ID가 없으면 원문 위치로 묶는다. */
export function splitFromSameSource(reqs: readonly AnalysedRequirement[]): Set<string> {
  const keyOf = (r: AnalysedRequirement) => JSON.stringify([r.source_id ?? null, r.source_ref])
  const counts = new Map<string, number>()
  for (const r of reqs) counts.set(keyOf(r), (counts.get(keyOf(r)) ?? 0) + 1)
  return new Set(reqs.filter((r) => (counts.get(keyOf(r)) ?? 0) > 1).map((r) => r.id))
}

/** 확인이 필요한 요구사항: 품질 경고·질문이 있거나, 같은 원문에서 나뉜 것 */
export function needsAttention(req: AnalysedRequirement, split: Set<string>): boolean {
  return req.quality_issues.length > 0 || split.has(req.id)
}

/** 확인할 것을 먼저, 같은 묶음 안에서는 받은 순서 */
export function sortRequirements(reqs: readonly AnalysedRequirement[]): AnalysedRequirement[] {
  const split = splitFromSameSource(reqs)
  return reqs
    .map((req, index) => ({ req, index, first: needsAttention(req, split) ? 0 : 1 }))
    .sort((a, b) => a.first - b.first || a.index - b.index)
    .map(({ req }) => req)
}

/** 처음에는 모두 유지 */
export function initialAnswers(reqs: readonly AnalysedRequirement[]): Answers {
  return Object.fromEntries(reqs.map((r) => [r.id, { action: 'keep' as const, texts: [] }]))
}

/** 답 종류를 바꿀 때 입력 칸을 채워 둔다: 수정은 지금 문장, 분할은 지금 문장 + 빈 칸 */
export function switchAction(req: AnalysedRequirement, action: Action): Answer {
  if (action === 'edit') return { action, texts: [req.text] }
  if (action === 'split') return { action, texts: [req.text, ''] }
  return { action, texts: [] }
}

/** 보내기 전에 막는 문제. 메시지는 서버 422처럼 요구사항 ID로 시작한다. */
export function problems(answers: Answers): string[] {
  const found: string[] = []
  for (const [reqId, { action, texts }] of Object.entries(answers)) {
    if (action === 'keep') continue
    if (action === 'split' && texts.length < 2) found.push(`${reqId}: 분할은 문장이 2개 이상이어야 합니다`)
    if (texts.some((t) => !t.trim())) found.push(`${reqId}: 빈 문장이 있습니다`)
  }
  return found
}

/** 보낼 답. 유지는 보내지 않는다(서버가 keep으로 본다). 문장 앞뒤 공백은 지운다. */
export function buildResponse(answers: Answers): RequirementsResponse {
  return {
    kind: 'requirements',
    answers: Object.entries(answers)
      .filter(([, a]) => a.action !== 'keep')
      .map(([req_id, a]) => ({ req_id, action: a.action, texts: a.texts.map((t) => t.trim()) })),
  }
}

/** 바꾼 요구사항 수 (화면 요약용) */
export function changedCount(answers: Answers): number {
  return Object.values(answers).filter((a) => a.action !== 'keep').length
}
