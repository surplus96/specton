import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import { dark } from '../../theme.ts'
import { positionsFrom, toElk, type EntityCard, type RelationshipLine } from './erd.ts'

// 가운데 「ERD 캔버스」 (#281). view design으로 엔티티 카드와 관계선을 직접 그린다(Mermaid 아님).
// 배치는 ELK(서버 개요와 같은 layered · 위→아래). 끌어서 옮긴 자리는 화면에서만 바뀌고 저장하지 않는다.
type CardData = { card: EntityCard; dimmed: boolean; lit: boolean }
type CardNode = Node<CardData, 'entity'>

function EntityNode({ data }: NodeProps<CardNode>) {
  const { card, dimmed, lit } = data
  return (
    <div className={`aiws-card${dimmed ? ' dimmed' : ''}${lit ? ' lit' : ''}`} style={{ width: card.width, overflow: 'hidden' }}>
      <Handle type="target" position={Position.Top} style={{ background: dark.line }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '8px 10px', borderBottom: `1px solid ${dark.border}` }}>
        <strong style={{ fontSize: 14 }}>{card.name}</strong>
        {card.findingCount > 0 && (
          <span className="aiws-chip" style={{ borderColor: '#fbbf24', color: '#fbbf24' }} title="이 엔티티를 가리키는 지적">
            ⚠ {card.findingCount}
          </span>
        )}
      </div>
      <div style={{ padding: '4px 0 6px' }}>
        {card.attributes.length === 0 && <div style={{ padding: '2px 10px', fontSize: 12, color: dark.inkMuted }}>속성 없음</div>}
        {card.attributes.map((a) => (
          <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '1px 10px', fontSize: 12, lineHeight: '20px' }}>
            <span style={{ width: 22, color: a.pk ? '#fbbf24' : dark.inkMuted, fontWeight: 700 }} aria-label={a.pk ? '기본 키' : undefined}>
              {a.pk ? 'PK' : a.uq ? 'UQ' : ''}
            </span>
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name}</span>
            <span style={{ color: dark.inkMuted }}>{a.type}</span>
            <span style={{ width: 34, textAlign: 'right', color: a.nullable ? dark.inkMuted : dark.ink }}>{a.nullable ? 'NULL' : 'NN'}</span>
          </div>
        ))}
      </div>
      <Handle type="source" position={Position.Bottom} style={{ background: dark.line }} />
    </div>
  )
}

const nodeTypes = { entity: EntityNode }

type Props = {
  cards: EntityCard[]
  lines: RelationshipLine[]
  selected: string | null
  /** 오른쪽 지적 목록에서 고른 대상. 바뀌면 그 엔티티로 부드럽게 이동한다 */
  focus: { id: string; at: number } | null
  onSelect: (id: string | null) => void
}

function Canvas({ cards, lines, selected, focus, onSelect }: Props) {
  const flow = useReactFlow()
  // ELK가 정한 자리와, 끌어서 옮긴 자리(화면에서만, 저장하지 않음)를 따로 둔다
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }> | null>(null)
  const [moved, setMoved] = useState<Record<string, { x: number; y: number }>>({})
  const [layoutError, setLayoutError] = useState(false)

  // ELK 배치: 큰 라이브러리라 이 화면에서만 불러온다
  useEffect(() => {
    let alive = true
    setLayoutError(false)
    import('elkjs/lib/elk.bundled.js')
      .then(({ default: ELK }) => new ELK().layout(toElk(cards, lines)))
      .then((laidOut) => {
        if (!alive) return
        setMoved({})
        setPositions(positionsFrom(cards, laidOut))
      })
      .catch(() => {
        if (!alive) return
        setLayoutError(true)
        setPositions(positionsFrom(cards, {}))
      })
    return () => {
      alive = false
    }
  }, [cards, lines])

  // 고른 엔티티와 관계로 이어진 엔티티만 밝게
  const lit = useMemo(() => {
    if (!selected) return null
    const ids = new Set([selected])
    for (const l of lines) {
      if (l.source === selected) ids.add(l.target)
      if (l.target === selected) ids.add(l.source)
    }
    return ids
  }, [selected, lines])

  const nodes = useMemo<CardNode[]>(() => {
    if (!positions) return []
    return cards.map((card) => ({
        id: card.id,
        type: 'entity',
        position: moved[card.id] ?? positions[card.id],
        data: { card, dimmed: lit !== null && !lit.has(card.id), lit: selected === card.id },
        width: card.width,
        height: card.height,
        selected: selected === card.id,
        ariaLabel: `엔티티 ${card.name}, 속성 ${card.attributes.length}개`,
      }))
  }, [positions, moved, cards, lit, selected])

  const edges = useMemo<Edge[]>(
    () =>
      lines.map((l) => {
        const on = selected !== null && (l.source === selected || l.target === selected)
        return {
          id: l.id,
          source: l.source,
          target: l.target,
          label: l.label,
          type: 'smoothstep',
          className: lit === null ? '' : on ? 'lit' : 'dimmed',
          style: { stroke: dark.line, strokeDasharray: l.identifying ? undefined : '6 4' },
        }
      }),
    [lines, selected, lit],
  )

  // 처음 배치가 끝나면 화면에 맞춘다
  useEffect(() => {
    if (positions) requestAnimationFrame(() => flow.fitView({ padding: 0.1, duration: 200 }))
  }, [positions, flow])

  // 지적에서 고른 대상으로 이동
  useEffect(() => {
    if (!focus || !positions?.[focus.id]) return
    const card = cards.find((c) => c.id === focus.id)
    const p = moved[focus.id] ?? positions[focus.id]
    if (card) flow.setCenter(p.x + card.width / 2, p.y + card.height / 2, { zoom: 1.1, duration: 250 })
    // 끌어서 옮긴 자리가 바뀔 때마다 다시 이동하지 않게 focus·배치만 본다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, positions, cards, flow])

  function onNodesChange(changes: NodeChange<CardNode>[]) {
    const next = applyNodeChanges(changes, nodes)
    const changed = changes.filter((c) => c.type === 'position').map((c) => c.id)
    if (changed.length === 0) return
    setMoved((prev) => ({ ...prev, ...Object.fromEntries(next.filter((n) => changed.includes(n.id)).map((n) => [n.id, n.position])) }))
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onSelect(null)
    else if (e.key === '+' || e.key === '=') flow.zoomIn({ duration: 150 })
    else if (e.key === '-') flow.zoomOut({ duration: 150 })
    else if (e.key === '0') flow.fitView({ padding: 0.1, duration: 200 })
    else return
    e.preventDefault()
  }

  return (
    <div style={{ height: '100%' }} onKeyDown={onKeyDown} aria-label="ERD 캔버스. 방향키로 고른 엔티티 이동, + - 0 으로 확대·축소·맞춤, Esc 선택 해제">
      {layoutError && (
        <div role="status" style={{ position: 'absolute', zIndex: 5, margin: 12, color: '#fbbf24', fontSize: 13 }}>
          자동 배치를 하지 못해 격자로 놓았습니다.
        </div>
      )}
      <ReactFlow<CardNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        minZoom={0.1}
        maxZoom={2}
        colorMode="dark"
      >
        <Background color={dark.border} gap={24} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable nodeColor={dark.card} nodeStrokeColor={dark.line} maskColor="rgba(2,6,23,0.6)" />
      </ReactFlow>
    </div>
  )
}

function ErdCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  )
}

export default ErdCanvas
