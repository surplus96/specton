import { useMemo } from 'react'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import { dark } from '../../theme.ts'
import { MINIMAP_STYLE, ariaLabels } from './flowText.ts'
import { pickedNode } from './select.ts'
import { COLUMNS, COLUMN_TITLE, MARK_LABEL, connected, type TraceGraph, type TraceNode } from './trace.ts'

// 가운데 「문서 추적」 (#281): 원문 → 요구사항 → 기능 → 엔티티 → 관계 → 지적을 열로 놓는다.
// 고른 항목과 앞뒤로 이어진 항목만 밝히고 나머지는 흐린다. 원문은 고치지 않는다 (ADR-0015).
type ItemData = { item: TraceNode; dimmed: boolean; lit: boolean }
type ItemNode = Node<ItemData, 'item'>

const COL_WIDTH = 230
const COL_GAP = 60
const ROW_HEIGHT = 86
/** 처음 화면·「0」 키로 맞출 줄 수. 항목이 많아도 글자를 읽을 수 있게 위쪽부터 보인다 */
const FIRST_ROWS = 7

const MARK_COLOR = { unlinked: 'var(--darktones-failed-fg)', excluded: 'var(--darktones-skipped-fg)', 'no-source': 'var(--darktones-awaiting-fg)' } as const

function ItemCard({ data }: NodeProps<ItemNode>) {
  const { item, dimmed, lit } = data
  return (
    <div className={`aiws-card${dimmed ? ' dimmed' : ''}${lit ? ' lit' : ''}`} style={{ width: COL_WIDTH, padding: '6px 10px', height: ROW_HEIGHT - 14 }}>
      <Handle type="target" position={Position.Left} style={{ visibility: 'hidden' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'center' }}>
        <strong style={{ fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</strong>
        {item.mark && (
          <span className="aiws-chip" style={{ borderColor: MARK_COLOR[item.mark], color: MARK_COLOR[item.mark] }}>
            {MARK_LABEL[item.mark]}
          </span>
        )}
      </div>
      <div
        style={{
          fontSize: 12,
          color: dark.inkMuted,
          marginTop: 2,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
      >
        {item.detail ?? '(원문 문장 없음)'}
      </div>
      <Handle type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { item: ItemCard }

type Props = {
  graph: TraceGraph
  selected: string | null
  onSelect: (key: string | null) => void
}

function Canvas({ graph, selected, onSelect }: Props) {
  const flow = useReactFlow()
  const lit = useMemo(() => (selected ? connected(graph, selected) : null), [graph, selected])

  const nodes = useMemo<ItemNode[]>(() => {
    const rowOf = new Map<string, number>()
    return graph.nodes.map((item) => {
      const col = COLUMNS.indexOf(item.column)
      const row = rowOf.get(item.column) ?? 0
      rowOf.set(item.column, row + 1)
      return {
        id: item.key,
        type: 'item',
        position: { x: col * (COL_WIDTH + COL_GAP), y: 36 + row * ROW_HEIGHT },
        data: { item, dimmed: lit !== null && !lit.has(item.key), lit: selected === item.key },
        width: COL_WIDTH,
        height: ROW_HEIGHT - 14,
        draggable: false,
        selected: selected === item.key,
        ariaLabel: `${COLUMN_TITLE[item.column]} ${item.title}${item.mark ? `, ${MARK_LABEL[item.mark]}` : ''}`,
      }
    })
  }, [graph, lit, selected])

  // 열 제목 (노드처럼 놓되 고를 수 없다)
  const headers = useMemo<Node[]>(
    () =>
      COLUMNS.map((c, i) => ({
        id: `head:${c}`,
        position: { x: i * (COL_WIDTH + COL_GAP), y: 0 },
        data: { label: COLUMN_TITLE[c] },
        selectable: false,
        draggable: false,
        focusable: false,
        style: { background: 'transparent', border: 'none', color: dark.inkMuted, fontWeight: 600, width: COL_WIDTH, padding: 0, fontSize: 18 },
      })),
    [],
  )

  const edges = useMemo<Edge[]>(
    () =>
      graph.edges.map((e) => {
        const on = lit !== null && lit.has(e.from) && lit.has(e.to)
        return {
          id: `${e.from}>${e.to}`,
          source: e.from,
          target: e.to,
          className: lit === null ? '' : on ? 'lit' : 'dimmed',
          style: { stroke: dark.line },
        }
      }),
    [graph, lit],
  )

  // 처음 보일 범위: 열 제목과 각 열의 위쪽 몇 줄
  const firstView = useMemo(
    () => ({
      padding: 0.04,
      nodes: [...headers, ...nodes.filter((n) => n.position.y < 36 + FIRST_ROWS * ROW_HEIGHT)].map((n) => ({ id: n.id })),
    }),
    // 항목 목록이 바뀔 때만 (선택으로 다시 맞추지 않음)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, headers],
  )

  // 위쪽 몇 줄에 맞춘 뒤 맨 위에 붙인다 (가운데에 두면 위가 비어 보임)
  function showTop(duration = 0) {
    void flow.fitView({ ...firstView, duration }).then(() => {
      const view = flow.getViewport()
      void flow.setViewport({ ...view, y: 16 }, { duration })
    })
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onSelect(null)
    else if (e.key === '+' || e.key === '=') flow.zoomIn({ duration: 150 })
    else if (e.key === '-') flow.zoomOut({ duration: 150 })
    else if (e.key === '0') showTop(200)
    else return
    e.preventDefault()
  }

  return (
    <div
      role="region"
      style={{ height: '100%' }}
      onKeyDown={onKeyDown}
      aria-label="문서 추적. Tab으로 항목 이동, Enter로 선택하면 이어진 앞뒤 항목이 강조됩니다. Esc 선택 해제"
    >
      <ReactFlow
        nodes={[...headers, ...nodes]}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, n) => !n.id.startsWith('head:') && onSelect(n.id === selected ? null : n.id)}
        onNodesChange={(changes) => {
          const picked = pickedNode(changes, selected)
          if (picked && !picked.startsWith('head:')) onSelect(picked)
        }}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        deleteKeyCode={null}
        edgesFocusable={false}
        ariaLabelConfig={ariaLabels(false)}
        nodesDraggable={false}
        onInit={() => showTop()}
        minZoom={0.1}
        colorMode="dark"
      >
        <Background color={dark.border} gap={24} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={dark.card} maskColor="var(--dark-mask)" style={MINIMAP_STYLE} />
      </ReactFlow>
    </div>
  )
}

function TraceCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  )
}

export default TraceCanvas
