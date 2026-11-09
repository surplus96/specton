// 결과 한눈에 보기의 숫자. 화면 코드(ResultSummary)와 분리해 테스트한다.
import type { DesignItem, Finding } from '../../api/viewItems.ts'

export type ResultCounts = {
  requirements: number
  functions: number
  entities: number
  relationships: number
  findings: number
  blocking: number
}

/** 설계·검토 결과의 개수. 요구사항은 기능이 이어 받은 요구사항 ID의 수(중복 제외)다. */
export function resultCounts(design: readonly DesignItem[], findings: readonly Finding[]): ResultCounts {
  const reqIds = new Set<string>()
  let functions = 0
  let entities = 0
  let relationships = 0
  for (const item of design) {
    if (item.type === 'function') {
      functions += 1
      item.req_ids.forEach((id) => reqIds.add(id))
    } else if (item.type === 'entity') entities += 1
    else relationships += 1
  }
  return {
    requirements: reqIds.size,
    functions,
    entities,
    relationships,
    findings: findings.length,
    blocking: findings.filter((f) => f.severity === 'critical').length,
  }
}
