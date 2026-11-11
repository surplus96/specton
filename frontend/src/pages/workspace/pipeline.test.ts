import { describe, expect, it } from 'vitest'
import type { ArtifactRef, DesignItem } from '../../api/viewItems.ts'
import { artifactBadge, pipelineStages, workspaceTab } from './pipeline.ts'
import { sqlReview } from '../review/sqlValidation.ts'

const fn = (id: string, req_ids: string[]) =>
  ({ type: 'function', id, name: id, description: '', priority: null, priority_source: 'unspecified', priority_rationale: null, req_ids, entity_ops: [] }) as DesignItem
const ent = (id: string) => ({ type: 'entity', id }) as unknown as DesignItem
const rel = (id: string) => ({ type: 'relationship', id }) as unknown as DesignItem
const art = (kind: ArtifactRef['kind'], file_format: ArtifactRef['file_format'], approved = false, extra: Partial<ArtifactRef> = {}): ArtifactRef => ({
  kind,
  file_format,
  revision: 1,
  hash: `h-${kind}`,
  approved,
  ...extra,
})

describe('산출물 파이프라인 카드', () => {
  it('다섯 단계를 순서대로, 숫자는 설계 결과에서 센다', () => {
    const stages = pipelineStages([fn('FN-01', ['REQ-01', 'REQ-02']), ent('E1'), ent('E2'), rel('R1')], [])
    expect(stages.map((s) => s.key)).toEqual(['requirements', 'functions', 'erd', 'ddl', 'rtm'])
    expect(stages[0].detail).toContain('2개')
    expect(stages[1].detail).toBe('기능 1개')
    expect(stages[2].detail).toBe('엔티티 2개 · 관계 1개')
  })

  it('파일이 없으면 미완성, 하나라도 초안이면 초안, 모두 승인본이면 승인본', () => {
    expect(artifactBadge([], 'erd')).toEqual({ tone: 'neutral', text: '미완성' })
    expect(artifactBadge([art('erd', 'mmd', true), art('erd', 'pdf', false)], 'erd').text).toBe('초안')
    expect(artifactBadge([art('erd', 'mmd', true), art('erd', 'pdf', true)], 'erd')).toEqual({ tone: 'success', text: '승인본' })
  })

  it('DDL 카드에는 검증 상태를 함께 보인다. 기록이 없으면 검증 전, 파일이 없으면 표시하지 않는다', () => {
    const ddl = (status?: NonNullable<ArtifactRef['validation']>['status']) =>
      pipelineStages([], status ? [art('ddl', 'sql', false, { validation: { status, validated_at: null } })] : [art('ddl', 'sql')])[3]
    expect(ddl('passed').extra).toEqual({ tone: 'success', text: '검증 통과' })
    expect(ddl('failed').extra).toEqual({ tone: 'danger', text: '검증 실패' })
    expect(ddl('error').extra?.text).toBe('검증 오류')
    expect(ddl().extra?.text).toBe('검증 전')
    expect(pipelineStages([], [])[3].extra).toBeNull()
  })

  it('DDL 검증 배지는 최종 검토 화면과 같은 규칙(sqlReview): 모르는 상태는 둘 다 검증 전', () => {
    const odd = [art('ddl', 'sql', false, { validation: { status: 'skipped', validated_at: null } as unknown as ArtifactRef['validation'] })]
    expect(sqlReview(odd, 1).status).toBe('unverified')
    expect(pipelineStages([], odd)[3].extra?.text).toBe('검증 전')
  })

  it('카드를 누르면 갈 탭. 주소의 tab 값이 이상하면 설계 탭', () => {
    expect(pipelineStages([], []).map((s) => s.tab)).toEqual(['design', 'design', 'erd', 'ddl', 'rtm'])
    expect(workspaceTab('erd')).toBe('erd')
    expect(workspaceTab('x')).toBe('design')
    expect(workspaceTab(null)).toBe('design')
  })
})
