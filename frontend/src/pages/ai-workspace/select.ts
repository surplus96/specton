import type { NodeChange } from '@xyflow/react'

/**
 * React Flow의 선택 변경에서 새로 고른 노드 ID (없으면 null).
 * 마우스 클릭은 onNodeClick으로 받지만, Tab으로 노드에 간 뒤 Enter·Space로 고르면 선택 변경만 온다 (#281 키보드 조작).
 */
export function pickedNode(changes: readonly NodeChange[], selected: string | null): string | null {
  for (const c of changes) if (c.type === 'select' && c.selected && c.id !== selected) return c.id
  return null
}
