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
  sortFindings,
  sourceText,
  targetText,
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
    expect(sourceText(finding('F', 'critical'))).toBe('규칙 검사 RULE-03')
    expect(sourceText(finding('F', 'major'))).toBe('A06 데이터 누락 검토')
  })

  it('대상 ID에 설계 이름을 붙인다 (속성은 엔티티.속성, 관계는 부모 → 자식)', () => {
    const names = nameIndex(design)
    expect(targetText({ kind: 'entity', id: 'ENT-01' }, names)).toBe('ENT-01 창고')
    expect(targetText({ kind: 'attribute', id: 'ATTR-01' }, names)).toBe('ATTR-01 창고.창고코드')
    expect(targetText({ kind: 'relationship', id: 'REL-01' }, names)).toBe('REL-01 창고 → 입고')
    expect(targetText({ kind: 'function', id: 'FN-99' }, names)).toBe('FN-99')
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
