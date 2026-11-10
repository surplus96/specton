import { describe, expect, it } from 'vitest'
import type { SseEvent } from '../../api/types.ts'
import type { AnalysedRequirement, ArtifactRef, DesignItem, ExtractionBlock, Finding } from '../../api/viewItems.ts'
import { payloadSummary, stepEvents, stepResult, type StepData } from './stepDetail.ts'

const ev = (id: number, event: SseEvent['event'], stage: string | null, payload?: Record<string, unknown>, revision = 0): SseEvent =>
  ({ id, event, data: { run_id: 'r', revision, stage, message: `m${id}`, payload } }) as SseEvent

const block = (id: string, status: ExtractionBlock['extraction_status'], decision: ExtractionBlock['user_decision'] = null) =>
  ({ block_id: id, extraction_status: status, user_decision: decision }) as ExtractionBlock

const req = (id: string, type: 'FR' | 'NFR', parent: string | null, kinds: string[] = []) =>
  ({ id, type, parent_id: parent, quality_issues: kinds.map((kind) => ({ kind, message: '', question: null })) }) as unknown as AnalysedRequirement

const finding = (id: string, source: 'rule' | 'llm', extra: Partial<Finding>) =>
  ({ id, source, severity: 'major', reviewer_id: null, rule_code: null, targets: [], ...extra }) as Finding

const data = (over: Partial<StepData> = {}): StepData => ({
  revision: 0,
  runRevision: 0,
  blocks: [],
  requirements: [],
  design: [],
  findings: [],
  artifacts: [],
  ...over,
})

const value = (rows: { label: string; value: string }[], label: string) => rows.find((r) => r.label === label)?.value

describe('stepEvents', () => {
  it('노드가 속한 단계의 이벤트만, 이벤트 ID 순서로 고른다', () => {
    const events = [ev(3, 'status', 'designing'), ev(1, 'status', 'parsing'), ev(2, 'status', 'analysing')]
    expect(stepEvents('a01', events, 0).map((e) => e.id)).toEqual([2])
    expect(stepEvents('a03', events, 0).map((e) => e.id)).toEqual([3])
  })

  it('고른 revision의 이벤트만 쓴다', () => {
    const events = [ev(1, 'status', 'designing', undefined, 0), ev(2, 'status', 'designing', undefined, 1)]
    expect(stepEvents('a02', events, 1).map((e) => e.id)).toEqual([2])
  })

  it('산출물 이벤트는 그 산출물 노드에만 붙는다', () => {
    const events = [ev(1, 'artifact', 'generating', { kind: 'ddl', file_format: 'sql' }), ev(2, 'artifact', 'generating', { kind: 'erd', file_format: 'mmd' })]
    expect(stepEvents('ddl', events, 0).map((e) => e.id)).toEqual([1])
    expect(stepEvents('erd', events, 0).map((e) => e.id)).toEqual([2])
  })
})

describe('payloadSummary', () => {
  it('알려진 칸을 사람이 읽는 글로 줄인다', () => {
    expect(payloadSummary({ kind: 'review', interrupt_id: 'i1', failed_branches: ['A07'], hitl_reason: 'rework_limit' })).toBe(
      '확인 요청: review · 빠진 관점: A07 · 멈춘 이유: rework_limit',
    )
    expect(payloadSummary({ info: 'skipped_sheets', sheets: ['표지', '목차'] })).toBe('건너뛴 시트: 표지, 목차')
    expect(payloadSummary({ code: 'LLM_UNAVAILABLE', retryable: true, detail: '키 없음' })).toBe('오류: LLM_UNAVAILABLE (다시 시도 가능) · 키 없음')
    expect(payloadSummary(undefined)).toBeNull()
  })
})

describe('stepResult', () => {
  it('문서 읽기·추출 확인: 판정별 블록 수와 결정', () => {
    const blocks = [block('b1', 'pass'), block('b2', 'review', 'confirmed'), block('b3', 'review', 'excluded'), block('b4', 'review')]
    expect(value(stepResult('parse', data({ blocks })), '블록')).toBe('4개 (정상 1 · 확인 필요 3 · 실패 0)')
    expect(value(stepResult('extraction_check', data({ blocks })), '결정')).toBe('확인 1 · 제외 1 · 결정 전 1')
  })

  it('A01: 기능·비기능, 분할, 품질 경고 종류별 수', () => {
    const requirements = [req('R1', 'FR', null, ['missing_value']), req('R2', 'NFR', 'R1', ['missing_value', 'ambiguous']), req('R3', 'FR', null)]
    const rows = stepResult('a01', data({ requirements }))
    expect(value(rows, '요구사항')).toBe('3개 (기능 2 · 비기능 1)')
    expect(value(rows, '분할')).toBe('1개')
    expect(value(rows, '품질 경고')).toBe('missing_value 2 · ambiguous 1')
  })

  it('A02·A03·A04: 설계 개수', () => {
    const design = [
      { type: 'function', id: 'F1', entity_ops: [{ entity_id: 'E1', operations: ['C', 'R'] }] },
      { type: 'entity', id: 'E1', attributes: [{ id: 'A1' }, { id: 'A2' }] },
      { type: 'relationship', id: 'R1', cardinality: 'N:M', optional: true, identifying: false },
    ] as unknown as DesignItem[]
    expect(value(stepResult('a02', data({ design })), '기능')).toBe('1개 (엔티티 조작 연결 1)')
    expect(value(stepResult('a03', data({ design })), '엔티티')).toBe('1개 (속성 2)')
    expect(value(stepResult('a04', data({ design })), '관계')).toBe('1개 (N:M 1 · 선택 1 · 식별 0)')
  })

  it('산출물: 형식·승인·DDL 검증 상태', () => {
    const artifacts = [
      { kind: 'ddl', file_format: 'sql', revision: 0, hash: 'abcdef0123456789', approved: false, validation: { status: 'passed' } },
    ] as unknown as ArtifactRef[]
    const rows = stepResult('ddl', data({ artifacts }))
    expect(value(rows, '파일')).toBe('sql 초안 (abcdef01)')
    expect(value(rows, 'SQL 검증')).toBe('passed')
    expect(value(stepResult('erd', data({ artifacts })), '파일')).toBe('아직 없음')
  })

  it('규칙·검토 관점: 출처별 지적 수', () => {
    const findings = [
      finding('f1', 'rule', { rule_code: 'RULE-02' }),
      finding('f2', 'rule', { rule_code: 'SC-03', severity: 'minor' }),
      finding('f3', 'llm', { reviewer_id: 'A06' }),
    ]
    expect(value(stepResult('rules', data({ findings })), '지적')).toBe('RULE 1 · SC 1')
    expect(value(stepResult('A06', data({ findings })), '지적')).toBe('1건 (주요 1)')
    expect(value(stepResult('A05', data({ findings })), '지적')).toBe('0건')
    expect(value(stepResult('normalize', data({ findings: [finding('f4', 'rule', { rule_code: 'RULE-03' })] })), '정리 지적')).toBe('1건')
  })

  it('A09: 재작업 횟수는 실행의 revision', () => {
    expect(value(stepResult('a09', data({ runRevision: 2 })), '재작업')).toBe('2회')
  })
})
