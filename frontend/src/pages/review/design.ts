// 설계 결과 표(기능·엔티티·관계)의 표시 규칙. 화면(DesignTables)과 분리해 테스트한다.
// 칸 뜻은 specton/contracts/design.py, docs/05를 따른다.
import type { DesignAttribute, DesignEntity, DesignFunction, DesignItem, DesignRelationship } from '../../api/viewItems.ts'

export function splitDesign(items: readonly DesignItem[]) {
  return {
    functions: items.filter((i): i is DesignFunction => i.type === 'function'),
    entities: items.filter((i): i is DesignEntity => i.type === 'entity'),
    relationships: items.filter((i): i is DesignRelationship => i.type === 'relationship'),
  }
}

/** 우선순위. 문서에 없어 추정한 값은 (추정)을 붙인다 */
export function priorityText(fn: Pick<DesignFunction, 'priority' | 'priority_source'>): string {
  if (!fn.priority) return '미지정'
  return fn.priority_source === 'inferred' ? `${fn.priority} (추정)` : fn.priority
}

/** 기능이 다루는 엔티티와 CRUD. 예: 「입고 C · 품목 R」 */
export function crudText(fn: Pick<DesignFunction, 'entity_ops'>, names: Map<string, string>): string {
  if (fn.entity_ops.length === 0) return '—'
  return fn.entity_ops.map((op) => `${names.get(op.entity_id) ?? op.entity_id} ${op.operations.join('')}`).join(' · ')
}

/** 속성 타입. 예: varchar(50), numeric(12,2) */
export function dataTypeText(a: Pick<DesignAttribute, 'data_type' | 'length' | 'precision' | 'scale'>): string {
  if (a.length != null) return `${a.data_type}(${a.length})`
  if (a.precision != null) return a.scale != null ? `${a.data_type}(${a.precision},${a.scale})` : `${a.data_type}(${a.precision})`
  return a.data_type
}

/** 키 표시. PK는 주 식별자, UNIQUE는 PK가 아닌 업무 키 */
export function keyText(a: Pick<DesignAttribute, 'is_key' | 'is_unique'>): string {
  return [a.is_key && 'PK', a.is_unique && 'UNIQUE'].filter(Boolean).join(', ') || '—'
}

/** 관계 성격. 예: 「1:N · 필수 · 비식별」 (색이 아니라 글로 보인다) */
export function relationText(r: Pick<DesignRelationship, 'cardinality' | 'optional' | 'identifying'>): string {
  return [r.cardinality, r.optional ? '선택' : '필수', r.identifying ? '식별' : '비식별'].join(' · ')
}
