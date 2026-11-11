// 최종 검토의 「산출물 확인 목록」 (시안: 기능 명세 · ERD · DDL · RTM). 화면 코드와 분리해 테스트한다.
// 실제로 만들어진 산출물만 ✓로 보이고, DDL은 SQL 검증 결과를 그대로 적는다(검증된 것처럼 꾸미지 않는다).
import type { ArtifactRef, DesignItem } from '../../api/viewItems.ts'
import { splitDesign } from './design.ts'
import type { SqlReview } from './sqlValidation.ts'

export type CheckRow = { key: 'functions' | 'erd' | 'ddl' | 'rtm'; title: string; detail: string; ok: boolean }

const SQL_TEXT: Record<SqlReview['status'], string> = {
  passed: 'SQL 검증 통과',
  failed: 'SQL 검증 실패',
  error: 'SQL 검증 실행 오류',
  unverified: 'SQL 미검증',
  missing: 'SQL 산출물 없음',
}

export function reviewChecklist(
  design: readonly DesignItem[],
  artifacts: readonly ArtifactRef[],
  revision: number,
  sql: SqlReview,
): CheckRow[] {
  const { functions, entities, relationships } = splitDesign(design)
  const has = (kind: ArtifactRef['kind']) => artifacts.some((a) => a.kind === kind && a.revision === revision)
  const reqs = new Set(functions.flatMap((f) => f.req_ids)).size
  return [
    {
      key: 'functions',
      title: '기능 명세',
      detail: `기능 ${functions.length}개 · 근거 요구사항 ${reqs}개`,
      ok: functions.length > 0,
    },
    {
      key: 'erd',
      title: 'ERD',
      detail: `엔티티 ${entities.length}개 · 관계 ${relationships.length}개${has('erd') ? '' : ' · 그림 없음'}`,
      ok: has('erd'),
    },
    { key: 'ddl', title: 'DDL', detail: SQL_TEXT[sql.status], ok: sql.status === 'passed' },
    { key: 'rtm', title: 'RTM', detail: has('rtm') ? '요구사항 · 기능 · 엔티티 연결' : '아직 없음', ok: has('rtm') },
  ]
}
