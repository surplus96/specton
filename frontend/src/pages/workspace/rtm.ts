// RTM 화면 미리보기 (결과 작업공간 「RTM」 탭). 화면 코드와 분리해 테스트한다.
// 정식 RTM은 서버가 만든 Excel·CSV 파일이다(specton/rtm_node.py). 화면은 받은 설계 값(req_ids·entity_ops)만으로
// 요구사항 → 기능 → 엔티티 연결을 보여 주고, 추정해서 메우지 않는다. 연결된 기능이 없으면 「미연결」.
import type { DesignItem } from '../../api/viewItems.ts'
import { splitDesign } from '../review/design.ts'

export type RtmRow = { reqId: string; functions: string[]; entities: string[]; linked: boolean }

export function rtmRows(design: readonly DesignItem[], requirementIds?: readonly string[]): RtmRow[] {
  const { functions, entities } = splitDesign(design)
  const order: string[] = []
  const add = (id: string) => {
    if (!order.includes(id)) order.push(id)
  }
  requirementIds?.forEach(add)
  functions.forEach((f) => f.req_ids.forEach(add))
  entities.forEach((e) => e.req_ids.forEach(add))

  return order.map((reqId) => {
    const fns = functions.filter((f) => f.req_ids.includes(reqId))
    const ents = new Set<string>()
    fns.forEach((f) => f.entity_ops.forEach((op) => ents.add(op.entity_id)))
    entities.filter((e) => e.req_ids.includes(reqId)).forEach((e) => ents.add(e.id))
    return { reqId, functions: fns.map((f) => f.id), entities: [...ents], linked: fns.length > 0 }
  })
}
