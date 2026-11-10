import type { SseEvent } from '../../api/types.ts'
import type { NodeState, PipelineNodeId } from './pipeline.ts'

export function nodeEvent(id: PipelineNodeId, events: readonly SseEvent[], revision: number): SseEvent | undefined {
  return events.filter((e) => e.event === 'status' && e.data.revision === revision && e.data.payload?.node === id)
    .reduce<SseEvent | undefined>((last, e) => !last || e.id > last.id ? e : last, undefined)
}

export function nodeState(event: SseEvent): NodeState {
  const p = event.data.payload
  if (p?.outcome === 'cancelled') return 'cancelled'
  if (p?.outcome === 'error') return 'failed'
  return p?.phase === 'finished' ? 'done' : 'running'
}
