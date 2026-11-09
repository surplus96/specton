// 산출물 파이프라인 카드(요구사항 → 기능 명세 → ERD → DDL → RTM)의 상태. 화면 코드와 분리해 테스트한다.
// 숫자는 /view 설계 결과에서, 상태는 /view 산출물 목록에서 정한다. 지어낸 지표(완성도 %)는 쓰지 않는다.
import type { ArtifactRef, DesignItem } from '../../api/viewItems.ts'
import type { Tone } from '../../theme.ts'
import type { ArtifactKind } from './rules.ts'
import { resultCounts } from './summary.ts'

/** 결과 작업공간의 탭 (주소 `&tab=`). 카드를 누르면 이 탭으로 간다. */
export type WorkspaceTab = 'design' | 'erd' | 'ddl' | 'rtm' | 'review'
export const WORKSPACE_TABS: readonly WorkspaceTab[] = ['design', 'erd', 'ddl', 'rtm', 'review']

export function workspaceTab(value: string | null): WorkspaceTab {
  return WORKSPACE_TABS.includes(value as WorkspaceTab) ? (value as WorkspaceTab) : 'design'
}

export type StageBadge = { tone: Tone; text: string }

export type PipelineStage = {
  key: 'requirements' | 'functions' | 'erd' | 'ddl' | 'rtm'
  code: string // 카드 위 작은 글자
  title: string
  detail: string // 한 줄 설명 (숫자)
  status: StageBadge
  extra: StageBadge | null // DDL 검증 상태
  tab: WorkspaceTab
}

const VALIDATION_BADGE: Record<NonNullable<ArtifactRef['validation']>['status'], StageBadge> = {
  passed: { tone: 'success', text: '검증 통과' },
  failed: { tone: 'danger', text: '검증 실패' },
  error: { tone: 'warning', text: '검증 오류' },
  unverified: { tone: 'neutral', text: '검증 전' },
}

/** 산출물 종류 하나의 상태: 파일이 없으면 미완성, 모두 승인본이면 승인본, 아니면 초안 */
export function artifactBadge(artifacts: readonly ArtifactRef[], kind: ArtifactKind): StageBadge {
  const mine = artifacts.filter((a) => a.kind === kind)
  if (mine.length === 0) return { tone: 'neutral', text: '미완성' }
  return mine.every((a) => a.approved) ? { tone: 'success', text: '승인본' } : { tone: 'warning', text: '초안' }
}

export function pipelineStages(design: readonly DesignItem[], artifacts: readonly ArtifactRef[]): PipelineStage[] {
  const c = resultCounts(design, [])
  const ddl = artifacts.find((a) => a.kind === 'ddl' && a.file_format === 'sql')
  return [
    {
      key: 'requirements',
      code: 'REQ',
      title: '요구사항',
      detail: `기능이 이어 받은 요구사항 ${c.requirements}개`,
      status: c.requirements > 0 ? { tone: 'success', text: '분석 완료' } : { tone: 'neutral', text: '없음' },
      extra: null,
      tab: 'design',
    },
    {
      key: 'functions',
      code: 'FUNC',
      title: '기능 명세',
      detail: `기능 ${c.functions}개`,
      status: artifactBadge(artifacts, 'functions'),
      extra: null,
      tab: 'design',
    },
    {
      key: 'erd',
      code: 'ERD',
      title: 'ERD',
      detail: `엔티티 ${c.entities}개 · 관계 ${c.relationships}개`,
      status: artifactBadge(artifacts, 'erd'),
      extra: null,
      tab: 'erd',
    },
    {
      key: 'ddl',
      code: 'DDL',
      title: 'DDL (SQL)',
      detail: ddl ? 'PostgreSQL 테이블 생성 SQL' : '아직 만들어지지 않았습니다',
      status: artifactBadge(artifacts, 'ddl'),
      extra: ddl ? VALIDATION_BADGE[ddl.validation?.status ?? 'unverified'] : null,
      tab: 'ddl',
    },
    {
      key: 'rtm',
      code: 'RTM',
      title: 'RTM (추적표)',
      detail: '요구사항 → 기능 → 엔티티 추적',
      status: artifactBadge(artifacts, 'rtm'),
      extra: null,
      tab: 'rtm',
    },
  ]
}
