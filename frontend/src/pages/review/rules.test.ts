// UI-06 최종 검토·설계 표 규칙 테스트. 화면 규칙이 서버(mock)와 맞는지까지 본다.
import { setupServer } from 'msw/node'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { createRun, getRun, getView, resumeRun, setApiBaseUrl } from '../../api/client.ts'
import { ApiError } from '../../api/errors.ts'
import type { ResumeRequest, RunStatus, SseEvent } from '../../api/types.ts'
import type { DesignItem, Finding } from '../../api/viewItems.ts'
import { createMockBackend } from '../../mocks/backend.ts'
import { crudText, dataTypeText, keyText, priorityText, relationText, splitDesign } from './design.ts'
import {
  buildResponse,
  canApprove,
  countBySeverity,
  nameIndex,
  problems,
  reviewNotices,
  reviewDiagnostics,
  severityGroups,
  sortFindings,
  sourceText,
  targetText,
  plainText,
} from './rules.ts'

const finding = (id: string, severity: Finding['severity'], extra: Partial<Finding> = {}): Finding => ({
  id,
  kind: 'k',
  severity,
  targets: [{ kind: 'entity', id: 'ENT-01' }],
  evidence: [{ req_id: 'REQ-01', quote: '인용' }],
  suggestion: '제안',
  target_stage: null,
  source: severity === 'critical' ? 'rule' : 'llm',
  reviewer_id: severity === 'critical' ? null : 'A06',
  rule_code: severity === 'critical' ? 'RULE-03' : null,
  fingerprint: id,
  iteration: 0,
  ...extra,
})

const design: DesignItem[] = [
  {
    type: 'function',
    id: 'FN-01',
    name: '입고 등록',
    description: '',
    priority: 'Must',
    priority_source: 'inferred',
    priority_rationale: null,
    req_ids: ['REQ-02'],
    entity_ops: [
      { entity_id: 'ENT-02', operations: ['C', 'R'] },
      { entity_id: 'ENT-01', operations: ['R'] },
    ],
  },
  {
    type: 'entity',
    id: 'ENT-01',
    pack: 'inventory',
    name: '창고',
    description: '',
    attributes: [
      {
        id: 'ATTR-01',
        name: '창고코드',
        description: null,
        data_type: 'varchar',
        length: 20,
        precision: null,
        scale: null,
        is_key: true,
        is_unique: false,
        nullable: false,
        req_ids: ['REQ-01'],
      },
    ],
    req_ids: ['REQ-01'],
    crud_exemptions: [],
  },
  { type: 'entity', id: 'ENT-02', pack: 'inventory', name: '입고', description: '', attributes: [], req_ids: ['REQ-02'], crud_exemptions: [] },
  {
    type: 'relationship',
    id: 'REL-01',
    parent: 'ENT-01',
    child: 'ENT-02',
    cardinality: '1:N',
    optional: true,
    identifying: false,
    rationale: '',
    req_ids: ['REQ-02'],
  },
]

describe('지적 표시', () => {
  it('차단 → 주요 → 참고, 같은 심각도는 받은 순서', () => {
    const list = [finding('F1', 'minor'), finding('F2', 'major'), finding('F3', 'critical'), finding('F4', 'major')]
    expect(sortFindings(list).map((f) => f.id)).toEqual(['F3', 'F2', 'F4', 'F1'])
    expect(countBySeverity(list)).toEqual({ critical: 1, major: 2, minor: 1 })
  })

  it('출처: 규칙 검사는 코드, LLM은 검토 관점 이름', () => {
    expect(sourceText(finding('F', 'critical'))).toBe('규칙 검사 · 키·데이터 종류')
    expect(sourceText(finding('F', 'major'))).toBe('데이터 누락 검토')
  })

  it('대상은 설계 이름만 보이고 내부 ID는 보이지 않는다 (속성은 테이블.항목, 관계는 부모 → 자식)', () => {
    const names = nameIndex(design)
    expect(targetText({ kind: 'entity', id: 'ENT-01' }, names)).toBe('창고')
    expect(targetText({ kind: 'attribute', id: 'ATTR-01' }, names)).toBe('창고.창고코드')
    expect(targetText({ kind: 'relationship', id: 'REL-01' }, names)).toBe('창고 → 입고')
    expect(targetText({ kind: 'function', id: 'FN-99' }, names)).toBe('기능')
  })

  it('서버 기술 식별자 안내만 정리하고 고객 인용·식별자는 보존한다', () => {
    const text = '명세번호 (ATTR-1a3d7a21b0e5807a): 표준 물리명 미확정. 기술 식별자 c_530ca3961c9de487c306f9b7 사용.'
    const generated = finding('F', 'minor', { source: 'rule', rule_code: 'RULE-05', kind: 'technical_identifier', targets: [{ kind: 'attribute', id: 'ATTR-1a3d7a21b0e5807a' }] })
    expect(plainText(text, generated)).toBe('명세번호: 표준 영문 이름을 아직 정하지 못했어요. 기술용 영문 이름을 썼어요.')
    expect(plainText(text, finding('F', 'major'))).toBe(text)
    expect(plainText(text, { ...generated, targets: [] })).toBe(text)
    const original = 'REQ-01 고객 코드 (ENT-123)와 t_ef11914c209eda772e3ab28f를 유지한다'
    expect(plainText(original, generated)).toBe(original)
    expect(targetText({ kind: 'requirement', id: 'REQ-01' }, new Map())).toBe('REQ-01')
  })

  it('불완전 검토·멈춘 이유는 지금 확인 요청의 interrupt 이벤트에서 읽는다', () => {
    const ev = (id: number, interruptId: string, payload: Record<string, unknown>): SseEvent => ({
      id,
      event: 'interrupt',
      data: { run_id: 'r', revision: 1, message: '최종 검토', payload: { kind: 'review', interrupt_id: interruptId, ...payload } },
    })
    const events = [ev(1, 'old', { failed_branches: ['A05'] }), ev(2, 'now', { failed_branches: ['A07'], hitl_reason: 'rework_limit' })]
    expect(reviewNotices(events, 'now')).toEqual({ failedBranches: ['A07'], hitlReason: 'rework_limit' })
    expect(reviewNotices(events, 'old')).toEqual({ failedBranches: ['A05'], hitlReason: null })
    expect(reviewNotices([], 'now')).toEqual({ failedBranches: [], hitlReason: null })
  })
})

describe('결정과 보내기', () => {
  it('차단 오류가 있으면 승인할 수 없다', () => {
    expect(canApprove([finding('F', 'major')])).toBe(true)
    expect(canApprove([finding('F', 'critical')])).toBe(false)
    expect(problems('approve', '', [finding('F', 'critical')])).toHaveLength(1)
    expect(problems('approve', '', [finding('F', 'major')])).toEqual([])
  })

  it('수정 요청은 내용이 필요하고, 보류는 메모 없이도 된다', () => {
    expect(problems('revise', '  ', [])).toEqual(['수정 요청 내용을 적어 주세요.'])
    expect(problems('hold', '', [])).toEqual([])
  })

  it('승인은 feedback을 빈 문자열로 보낸다 (필수 칸, 강의 07)', () => {
    expect(buildResponse('approve', '무시됨')).toEqual({ kind: 'review', decision: 'approve', feedback: '' })
    expect(buildResponse('revise', ' 입고 PK 추가 ')).toEqual({ kind: 'review', decision: 'revise', feedback: '입고 PK 추가' })
  })
})

describe('설계 표', () => {
  const names = nameIndex(design)
  const { functions, entities, relationships } = splitDesign(design)

  it('type으로 나눈다', () => {
    expect([functions.length, entities.length, relationships.length]).toEqual([1, 2, 1])
  })

  it('우선순위·CRUD·타입·키·관계 표시', () => {
    expect(priorityText(functions[0])).toBe('Must (추정)')
    expect(priorityText({ priority: null, priority_source: 'unspecified' })).toBe('미지정')
    expect(crudText(functions[0], names)).toBe('입고 CR · 창고 R')
    expect(dataTypeText(entities[0].attributes[0])).toBe('varchar(20)')
    expect(dataTypeText({ data_type: 'numeric', length: null, precision: 12, scale: 2 })).toBe('numeric(12,2)')
    expect(keyText(entities[0].attributes[0])).toBe('PK')
    expect(keyText({ is_key: false, is_unique: false })).toBe('—')
    expect(relationText(relationships[0])).toBe('1:N · 선택 · 비식별')
  })
})

describe('서버(mock)와 같은 결과', () => {
  const server = setupServer()
  beforeAll(() => {
    setApiBaseUrl('http://specton.test')
    server.listen({ onUnhandledRequest: 'error' })
  })
  afterAll(() => server.close())
  beforeEach(() => server.resetHandlers(...createMockBackend({ stepMs: 0 }).handlers))

  const answer = (run: RunStatus, response: ResumeRequest['response']) =>
    resumeRun(run.run_id, { interrupt_id: run.interrupt!.interrupt_id, expected_revision: run.revision, response })

  /** quick 시나리오는 확인 화면 없이 바로 최종 검토까지 간다 */
  async function atReview(name: string) {
    const created = await createRun(new File(['내용'], name), 'inventory')
    const run = await getRun(created.run_id)
    expect(run.interrupt?.kind).toBe('review')
    const findings = (await getView(run.run_id, 'review')).items as Finding[]
    return { run, findings }
  }

  it('차단 오류가 없으면 승인되어 내보낸다', async () => {
    const { run, findings } = await atReview('재고_quick.csv')
    expect(canApprove(findings)).toBe(true)
    expect((await answer(run, buildResponse('approve', ''))).status).toBe('exporting')
  })

  it('critical: 화면이 막는 승인은 서버도 422, 수정 요청 뒤에는 승인할 수 있다', async () => {
    // critical 시나리오는 quick이 아니라 확인 화면(추출·분석)을 거쳐 최종 검토에 온다
    const { run, findings } = await atReviewThroughChecks('재고_critical.csv')
    expect(canApprove(findings)).toBe(false)
    const err = await answer(run, buildResponse('approve', '')).catch((e: unknown) => e)
    expect((err as ApiError).status).toBe(422)
    expect((err as ApiError).message).toBe('차단 오류가 남아 있어 승인할 수 없습니다.')

    expect((await answer(run, buildResponse('revise', '입고 PK를 정해 주세요'))).revision).toBe(run.revision + 1)
    const again = await getRun(run.run_id)
    const after = (await getView(run.run_id, 'review')).items as Finding[]
    expect(canApprove(after)).toBe(true)
    expect((await answer(again, buildResponse('approve', ''))).status).toBe('exporting')
  })

  it('보류는 같은 확인 요청으로 계속 기다린다', async () => {
    const { run } = await atReview('재고_quick.csv')
    const held = await answer(run, buildResponse('hold', ''))
    expect(held.status).toBe('awaiting_review')
    expect(held.interrupt?.interrupt_id).toBe(run.interrupt?.interrupt_id)
  })

  /** 추출 확인(실패 블록 제외) → 분석 확인(그대로) → 최종 검토 */
  async function atReviewThroughChecks(name: string) {
    const created = await createRun(new File(['내용'], name), 'inventory')
    let run = await getRun(created.run_id)
    await answer(run, { kind: 'extraction', confirmed: true, excluded_blocks: [{ block_id: 'B5', reason: null }] })
    run = await getRun(created.run_id)
    await answer(run, { kind: 'requirements', answers: [] })
    run = await getRun(created.run_id)
    expect(run.interrupt?.kind).toBe('review')
    const findings = (await getView(run.run_id, 'review')).items as Finding[]
    return { run, findings }
  }
})

describe('검토가 필요한 항목 요약', () => {
  const f = (id: string, severity: Finding['severity'], ...targets: string[]) =>
    ({ id, severity, targets: targets.map((t) => ({ kind: 'entity', id: t })) }) as unknown as Finding
  const names = new Map([
    ['ENT-1', '입고'],
    ['ENT-2', '창고'],
  ])

  it('심각도마다 건수와 대표 대상, 없는 심각도는 빼고 차단 → 주요 → 참고 순서', () => {
    const groups = severityGroups([f('F3', 'minor', 'ENT-2'), f('F1', 'critical', 'ENT-1', 'ENT-2'), f('F2', 'critical', 'ENT-1')], names)
    expect(groups).toEqual([
      { severity: 'critical', count: 2, sample: '입고 외 1개' },
      { severity: 'minor', count: 1, sample: '창고' },
    ])
  })

  it('이름을 모르면 ID, 대상이 없으면 「대상 없음」, 지적이 없으면 빈 목록', () => {
    expect(severityGroups([f('F1', 'major', 'ENT-9')], names)[0].sample).toBe('ENT-9')
    expect(severityGroups([f('F1', 'major')], names)[0].sample).toBe('대상 없음')
    expect(severityGroups([], names)).toEqual([])
  })
})


it('제외 사유·A09 판단은 현재 interrupt만 표시하고 이전 기록에도 대응한다', () => {
  const ev = (id: number, interruptId: string, payload: Record<string, unknown>): SseEvent => ({
    id, event: 'interrupt', data: { run_id: 'r', revision: 2, message: '', payload: { kind: 'review', interrupt_id: interruptId, ...payload } },
  })
  const events = [ev(1, 'old', { rejected_findings: [{ finding_id: 'old', reason: 'unknown_target' }] }), ev(2, 'now', {
    rejected_findings: [{ finding_id: 'A07-1', reviewer_id: 'A07', reason: 'quote_not_found' }, null],
    router_decision: { revision: 1, stage: null, rationale: null, error_code: 'LLM_TIMEOUT' },
  })]
  const messages = reviewDiagnostics(events, 'now')
  expect(messages).toHaveLength(2)
  expect(messages[0]).toBe('근거가 확인되지 않은 의견 1건은 뺐어요.')
  expect(messages[1]).toBe('다시 설계할 곳: 판단 불가 (2차 설계안 기준).')
  expect(reviewDiagnostics(events, undefined)).toEqual([])
  expect(reviewDiagnostics([ev(3, 'legacy', {})], 'legacy')).toEqual([])
  expect(reviewDiagnostics([ev(4, 'answer', { router_decision: { revision: 2, stage: 'functions', rationale: '기능 책임 누락', error_code: null } })], 'answer')[0]).toContain('기능 책임 누락')
})
