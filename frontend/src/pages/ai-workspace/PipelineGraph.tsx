import { useMemo } from 'react'
import { Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import { darkTones } from '../../theme.ts'
import { pickedNode } from './select.ts'
import { KIND_LABEL, STATE_LABEL, pipelineEdges, type PipelineNode } from './pipeline.ts'

// 왼쪽 「실행 단계 그래프」 (#281). 위→아래로 고정 배치하고 끌지 않는다.
// 상태는 색만이 아니라 아이콘·글자로도 보인다. 진행 중·확인 대기 노드는 은은하게 맥박친다.
type StepData = { node: PipelineNode }
type StepNode = Node<StepData, 'step'>
type SpacerNode = Node<Record<string, never>, 'spacer'>
type FlowNode = StepNode | SpacerNode

const ROW = 64
const SINGLE_WIDTH = 236
const LANE_WIDTH = { 3: 74, 4: 54 } as const

function StepCard({ data }: NodeProps<StepNode>) {
  const { node } = data
  const tone = darkTones[node.state]
  const state = STATE_LABEL[node.state]
  const narrow = node.lane !== undefined
  return (
    <div
      className={`aiws-card aiws-tip state-${node.state}`}
      data-tip={`${node.title} · ${state.text}${node.note ? ` · ${node.note}` : ''} · ${KIND_LABEL[node.kind]}`}
      style={{ borderColor: tone.border, padding: narrow ? '4px 6px' : '6px 10px', width: '100%', height: '100%' }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: 'hidden' }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: narrow ? 11 : 13, fontWeight: 600 }}>
        <span className={`aiws-state-icon state-${node.state}`} style={{ color: tone.fg }} aria-hidden="true">
          {state.icon}
        </span>
        {/* 좁은 갈래 칸은 번호만 (A05·DDL), 전체 이름은 툴팁·상세 패널에 */}
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{narrow ? node.title.split(' ')[0] : node.title}</span>
      </div>
      {!narrow && (
        <div style={{ display: 'flex', gap: 6, marginTop: 2, fontSize: 11, color: tone.fg }}>
          <span>{state.text}</span>
          <span style={{ color: 'var(--aiws-ink-muted)' }}>· {KIND_LABEL[node.kind]}</span>
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: 'hidden' }} />
      {/* 재작업 선은 오른쪽으로 돌아 올라가 다른 선·카드와 겹치지 않게 한다 */}
      <Handle id="side-out" type="source" position={Position.Right} style={{ visibility: 'hidden' }} />
      <Handle id="side-in" type="target" position={Position.Right} style={{ visibility: 'hidden' }} />
    </div>
  )
}

const nodeTypes = { step: StepCard, spacer: () => <div style={{ width: 1, height: 1 }} /> }

type Props = {
  nodes: PipelineNode[]
  selected: string | null
  onSelect: (id: string | null) => void
}

function PipelineGraph({ nodes, selected, onSelect }: Props) {
  const flowNodes = useMemo<FlowNode[]>(() => {
    // 단계가 오기 전에는 비워 둔다 (빈 칸 하나에 맞춰 크게 확대되지 않게)
    if (!nodes.length) return []
    const lanes = new Map<number, number>()
    for (const n of nodes) if (n.lane !== undefined) lanes.set(n.step, (lanes.get(n.step) ?? 0) + 1)
    // 오른쪽으로 도는 재작업 선과 그 글자가 잘리지 않게, 맞춤(fitView) 범위를 넓히는 보이지 않는 칸
    const spacer: SpacerNode = {
      id: 'spacer',
      type: 'spacer',
      position: { x: SINGLE_WIDTH + 40, y: 0 },
      data: {},
      width: 1,
      height: 1,
      style: { pointerEvents: 'none' },
      draggable: false,
      selectable: false,
      focusable: false,
    }
    return [spacer, ...nodes.map((n): StepNode => {
      const count = lanes.get(n.step)
      const width = count ? LANE_WIDTH[count as 3 | 4] : SINGLE_WIDTH
      const gap = 6
      const x = count ? (n.lane ?? 0) * (width + gap) - ((count * (width + gap) - gap) - SINGLE_WIDTH) / 2 : 0
      return {
        id: n.id,
        type: 'step',
        position: { x, y: n.step * ROW },
        data: { node: n },
        width,
        height: count ? 34 : 48,
        draggable: false,
        selected: selected === n.id,
        ariaLabel: `${n.title}: ${STATE_LABEL[n.state].text}`,
      }
    })]
  }, [nodes, selected])

  const edges = useMemo<Edge[]>(
    () =>
      pipelineEdges().map((e) => ({
        id: `${e.from}-${e.to}`,
        source: e.from,
        target: e.to,
        ...(e.rework ? { sourceHandle: 'side-out', targetHandle: 'side-in' } : {}),
        animated: e.rework,
        style: { stroke: 'var(--aiws-line)', strokeDasharray: e.rework ? '4 4' : undefined },
        label: e.rework ? '재작업' : undefined,
        type: e.rework ? 'smoothstep' : 'straight',
      })),
    [],
  )

  return (
    <div role="region" style={{ height: 14 * ROW + 40 }} aria-label="실행 단계 그래프. Tab으로 단계 이동, Enter로 선택">
      <ReactFlow<FlowNode>
        nodes={flowNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.08 }}
        nodesDraggable={false}
        nodesConnectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        onNodeClick={(_, n) => n.id !== 'spacer' && onSelect(n.id === selected ? null : n.id)}
        onNodesChange={(changes) => {
          const picked = pickedNode(changes, selected)
          if (picked && picked !== 'spacer') onSelect(picked)
        }}
      />
    </div>
  )
}

export default PipelineGraph
