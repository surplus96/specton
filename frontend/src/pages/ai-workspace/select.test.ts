import { describe, expect, it } from 'vitest'
import { pickedNode } from './select.ts'

describe('키보드 선택', () => {
  it('Enter·Space로 고른 노드(선택 변경)를 앱 선택으로 넘긴다', () => {
    expect(pickedNode([{ type: 'select', id: 'E1', selected: true }], null)).toBe('E1')
  })

  it('선택 해제·이미 고른 노드·위치 변경은 넘기지 않는다', () => {
    expect(pickedNode([{ type: 'select', id: 'E1', selected: false }], null)).toBeNull()
    expect(pickedNode([{ type: 'select', id: 'E1', selected: true }], 'E1')).toBeNull()
    expect(pickedNode([{ type: 'position', id: 'E1', position: { x: 1, y: 2 } }], null)).toBeNull()
  })
})
