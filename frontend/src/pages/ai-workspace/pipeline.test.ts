import { describe, expect, it } from 'vitest'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { ArtifactRef, Finding } from '../../api/viewItems.ts'
import { SKIPPED_REQUIREMENTS_MESSAGE } from '../run/screens.ts'
import { PIPELINE, pipelineEdges, pipelineNodes, pipelineProgress, type NodeState, type PipelineInput } from './pipeline.ts'

type Run = PipelineInput['run']
const run = (status: RunStatus['status'], extra: Partial<Run> = {}): Run => ({
  status,
  stage: status,
  revision: 0,
  interrupt: null,
  ...extra,
})
let id = 0
const event = (name: SseEvent['event'], stage: string, message = '', payload: Record<string, unknown> = {}): SseEvent =>
  ({ id: ++id, event: name, data: { run_id: 'r', revision: 0, stage, message, payload } }) as unknown as SseEvent
const art = (kind: ArtifactRef['kind'], revision = 0): ArtifactRef => ({ kind, file_format: 'sql', revision, hash: 'h', approved: false })
const llm = (reviewer: string): Finding => ({ source: 'llm', reviewer_id: reviewer, severity: 'minor' }) as Finding

function states(input: Partial<PipelineInput> & { run: Run }): Record<string, NodeState> {
  const nodes = pipelineNodes({ events: [], artifacts: [], findings: [], ...input })
  return Object.fromEntries(nodes.map((n) => [n.id, n.state]))
}

describe('실행 단계 그래프: 모양', () => {
  it('문서 읽기부터 내보내기까지, 생성 3갈래·검토 4갈래가 갈라졌다 모인다', () => {
    expect(PIPELINE.map((d) => d.id)[0]).toBe('parse')
    expect(PIPELINE.slice(-1)[0].id).toBe('export')
    const edges = pipelineEdges()
    expect(edges.filter((e) => e.from === 'normalize').map((e) => e.to)).toEqual(['ddl', 'erd', 'rtm'])
    expect(edges.filter((e) => e.to === 'rules').map((e) => e.from)).toEqual(['ddl', 'erd', 'rtm'])
    expect(edges.filter((e) => e.from === 'rules').map((e) => e.to)).toEqual(['A05', 'A06', 'A07', 'A08'])
    expect(edges.filter((e) => e.rework)).toEqual([{ from: 'a09', to: 'a02', rework: true }])
  })
})

describe('실행 단계 그래프: 상태', () => {
  it('대기 중이면 모두 대기', () => {
    expect(new Set(Object.values(states({ run: run('queued', { stage: null }) })))).toEqual(new Set(['waiting']))
  })

  it('문서 읽기 중: 문서 읽기만 진행, 뒤는 대기', () => {
    const s = states({ run: run('parsing') })
    expect(s.parse).toBe('running')
    expect(s.a01).toBe('waiting')
  })

  it('추출 확인을 기다리면 앞은 완료, 추출 확인은 확인 대기', () => {
    const s = states({ run: run('awaiting_input', { interrupt: { interrupt_id: 'i', kind: 'extraction', message: '' } }) })
    expect([s.parse, s.extraction_check, s.a01]).toEqual(['done', 'awaiting', 'waiting'])
  })

  it('확인할 것이 없어 지나간 사람 확인은 건너뜀 (ADR-0015)', () => {
    const events = [event('status', 'designing', SKIPPED_REQUIREMENTS_MESSAGE)]
    const s = states({ run: run('designing'), events })
    expect(s.extraction_check).toBe('skipped') // 추출 확인 요청 이벤트가 없었다
    expect(s.requirements_check).toBe('skipped')
    expect([s.a02, s.a03, s.a04, s.normalize]).toEqual(['running', 'running', 'running', 'running'])
  })

  it('물어봤던 추출 확인은 지나가면 완료', () => {
    const events = [event('interrupt', 'awaiting_input', '', { kind: 'extraction', interrupt_id: 'i' })]
    expect(states({ run: run('analysing'), events }).extraction_check).toBe('done')
  })

  it('생성 중: 그 revision의 산출물이 있는 가지만 완료', () => {
    const s = states({ run: run('generating', { revision: 1 }), artifacts: [art('erd', 1), art('ddl', 0)] })
    expect([s.ddl, s.erd, s.rtm]).toEqual(['running', 'done', 'running']) // ddl은 지난 revision 것
    expect(s.a09).toBe('done') // revision 1 = 재작업 한 번
  })

  it('검토 중: 지적을 낸 리뷰어는 완료', () => {
    const s = states({ run: run('reviewing'), findings: [llm('A06')] })
    expect([s.A05, s.A06, s.A07, s.A08]).toEqual(['running', 'done', 'running', 'running'])
  })

  it('최종 검토 대기: 빠진 검토 관점은 실패, 재작업이 없었으면 A09 건너뜀', () => {
    const interrupt = { interrupt_id: 'i', kind: 'review' as const, message: '' }
    const events = [event('interrupt', 'awaiting_review', '', { kind: 'review', interrupt_id: 'i', failed_branches: ['A07'] })]
    const s = states({ run: run('awaiting_review', { interrupt }), events })
    expect([s.A05, s.A07, s.a09, s.final_review, s.export]).toEqual(['done', 'failed', 'skipped', 'awaiting', 'waiting'])
  })

  it('완료: 모두 완료(건너뛴 것 제외)', () => {
    const nodes = pipelineNodes({ run: run('completed', { stage: null }), events: [], artifacts: [], findings: [] })
    expect(nodes.find((n) => n.id === 'export')!.state).toBe('done')
    expect(pipelineProgress(nodes)).toEqual({ done: nodes.length - 2, total: nodes.length - 2 }) // 추출 확인·A09 건너뜀
  })

  it('실패: 서버가 stage를 비워도 마지막 진행 이벤트의 단계에 실패, 뒤는 도달하지 않음', () => {
    const events = [event('status', 'parsing'), event('status', 'analysing')]
    const nodes = pipelineNodes({ run: run('failed', { stage: null }), events, artifacts: [], findings: [] })
    const by = Object.fromEntries(nodes.map((n) => [n.id, n]))
    expect(by.parse.state).toBe('done')
    expect(by.a01.state).toBe('failed')
    expect(by.a02.state).toBe('waiting')
    expect(by.a02.note).toBe('도달하지 않음')
  })

  it('생성 중 취소: 이미 만든 가지는 완료, 나머지는 취소', () => {
    const events = [event('status', 'generating')]
    const s = states({ run: run('cancelled', { stage: null }), events, artifacts: [art('rtm')] })
    expect([s.ddl, s.erd, s.rtm]).toEqual(['cancelled', 'cancelled', 'done'])
  })
})
