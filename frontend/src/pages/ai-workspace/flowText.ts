import type { AriaLabelConfig } from '@xyflow/react'

// React Flow 화면 낭독 안내를 한국어로 (#281 후속). 기본 영어 문구는 「Delete로 지우기」를 안내하지만
// 이 페이지는 조회만 하므로 지우기·연결 안내를 넣지 않는다. 삭제 키는 각 캔버스에서 deleteKeyCode={null}로 끈다.
const DIRECTION: Record<string, string> = { up: '위', down: '아래', left: '왼쪽', right: '오른쪽' }

/** movable: 고른 카드를 방향키로 옮길 수 있는 캔버스(ERD)인가 */
export function ariaLabels(movable: boolean): Partial<AriaLabelConfig> {
  const select = movable
    ? 'Enter나 Space로 골라요. 고른 뒤 방향키로 옮길 수 있고, Esc로 선택을 풀어요.'
    : 'Enter나 Space로 골라요. Esc로 선택을 풀어요.'
  return {
    'node.a11yDescription.default': select,
    'node.a11yDescription.keyboardDisabled': select,
    'node.a11yDescription.ariaLiveMessage': ({ direction, x, y }) =>
      `고른 카드를 ${DIRECTION[direction] ?? direction}으로 옮겼어요. 새 위치 x ${Math.round(x)}, y ${Math.round(y)}`,
    'edge.a11yDescription.default': '연결선이에요. 고르거나 지울 수 없어요.',
    'controls.ariaLabel': '확대·축소 버튼',
    'controls.zoomIn.ariaLabel': '확대',
    'controls.zoomOut.ariaLabel': '축소',
    'controls.fitView.ariaLabel': '화면에 맞추기',
    'controls.interactive.ariaLabel': '잠금',
    'minimap.ariaLabel': '미니맵',
    'handle.ariaLabel': '연결점',
  }
}

/** 미니맵: 카드를 덜 가리게 작고 반투명하게. 마우스를 올리면 진해진다 (aiWorkspace.css) */
export const MINIMAP_STYLE = { width: 150, height: 100 } as const
