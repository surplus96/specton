import { useEffect, useMemo, useState } from 'react'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus, SseEvent } from '../../api/types.ts'
import type { ExtractionBlock } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import type { Tone } from '../../theme.ts'
import Button from '../../ui/Button.tsx'
import ConfirmButton from '../../ui/ConfirmButton.tsx'
import DataTable, { type Column } from '../../ui/DataTable.tsx'
import Lines from '../../ui/Lines.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import Segmented from '../../ui/Segmented.tsx'
import { useResume } from '../run/useResume.ts'
import {
  STATUS_LABEL,
  STOP_RESPONSE,
  blockLabel,
  buildResponse,
  initialDecisions,
  locationText,
  problems,
  relatedWarnings,
  skippedSheets,
  sortBlocks,
  type Decision,
  type Decisions,
} from './rules.ts'

// UI-02 추출 확인 (docs/09, ADR-0015).
// 원문은 고치지 않고 확인 또는 제외만 한다. 확인할 블록(실패·확인 필요)을 먼저 보인다.
// - 확인 필요(review): 확인 또는 제외. 제외하면 사유 필수
// - 실패(fail): 제외만 가능. 남아 있으면 보낼 수 없다
// 직접 누른 수를 「n / N 확인」으로 보이고, 모두 누르면 보내기 버튼이 라임으로 바뀐다(시안).
// 누르지 않은 확인 필요 블록은 서버가 「확인」으로 본다 (rules.ts buildResponse).
type Props = {
  run: RunStatus
  events: SseEvent[]
  onChanged: () => Promise<void>
  label: string
}

const STATUS_TONE: Record<ExtractionBlock['extraction_status'], Tone> = {
  fail: 'danger',
  review: 'warning',
  pass: 'neutral',
}

function ExtractionPanel({ run, events, onChanged, label }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [blocks, setBlocks] = useState<ExtractionBlock[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [decisions, setDecisions] = useState<Decisions>({})
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const { send, sending, error: actionError, notice, reloadKey, reload, canAnswer } = useResume(run, onChanged)

  // 확인 요청이 바뀌면(다른 곳에서 답한 뒤 새 요청 등) 블록을 다시 읽고 결정을 처음으로 돌린다
  useEffect(() => {
    let alive = true
    setBlocks(null)
    setLoadError(null)
    setTouched(new Set())
    getView(run.run_id, 'extraction', run.revision)
      .then((view) => {
        if (!alive) return
        const items = view.items as ExtractionBlock[]
        setBlocks(items)
        setDecisions(initialDecisions(items))
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, interruptId, reloadKey])

  const sorted = useMemo(() => (blocks ? sortBlocks(blocks) : []), [blocks])
  const toCheck = sorted.filter((b) => b.extraction_status !== 'pass')
  const passed = sorted.filter((b) => b.extraction_status === 'pass')
  const failCount = toCheck.filter((b) => b.extraction_status === 'fail').length
  const reviewCount = toCheck.length - failCount
  const blocking = blocks ? problems(blocks, decisions) : []
  const warnings = blocks ? relatedWarnings(blocks, decisions) : []
  const blockName = (blockId: string) => {
    const b = blocks?.find((x) => x.block_id === blockId)
    return b ? blockLabel(b) : blockId
  }
  const sheets = skippedSheets(events.map((e) => e.data.payload))
  const decided = toCheck.filter((b) => touched.has(b.block_id)).length
  const allDecided = toCheck.length > 0 && decided === toCheck.length

  const decide = (blockId: string, change: Partial<Decision>) => {
    setDecisions((prev) => ({ ...prev, [blockId]: { ...prev[blockId], ...change } }))
    setTouched((prev) => new Set(prev).add(blockId))
  }

  const baseColumns: Column<ExtractionBlock>[] = [
    {
      key: 'status',
      title: '판정',
      width: 96,
      render: (b) => <StatusTag tone={STATUS_TONE[b.extraction_status]}>{STATUS_LABEL[b.extraction_status]}</StatusTag>,
    },
    {
      key: 'ref',
      title: '원문 위치',
      width: 150,
      render: (b) => (
        <div className="stack-sm" style={{ gap: 2 }}>
          <span>{locationText(b.source_ref)}</span>
          {b.source_id && (
            <span className="mono subtle" style={{ fontSize: 12 }}>
              {b.source_id}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'text',
      title: '원문 문장',
      render: (b) => (b.source_text === null ? <span className="subtle">원문 없음</span> : <Lines text={b.source_text} />),
    },
    { key: 'notice', title: '판정 이유', width: 240, render: (b) => (b.notice ? <Lines text={b.notice} /> : '—') },
  ]

  const decisionColumn: Column<ExtractionBlock> = {
    key: 'decision',
    title: '결정',
    width: 230,
    render: (b) => {
      const d = decisions[b.block_id] ?? { exclude: false, reason: '' }
      const isReview = b.extraction_status === 'review'
      const reasonMissing = isReview && d.exclude && !d.reason.trim()
      const value = touched.has(b.block_id) || d.exclude ? (d.exclude ? 'exclude' : 'confirm') : null
      return (
        <div className="stack-sm">
          <Segmented<'exclude' | 'confirm'>
            variant="choice"
            label={`${blockLabel(b)} 결정`}
            value={value}
            onChange={(v) => decide(b.block_id, { exclude: v === 'exclude' })}
            options={[
              { value: 'exclude', label: '제외' },
              { value: 'confirm', label: '확인', disabled: !isReview, title: isReview ? undefined : '실패한 원문은 제외만 할 수 있어요' },
            ]}
          />
          {!isReview && !d.exclude && <span className="subtle" style={{ fontSize: 13 }}>실패한 원문은 제외만 할 수 있어요</span>}
          {value === 'confirm' && (
            <span className="row" style={{ gap: 6, fontSize: 13, fontWeight: 600 }}>
              <Icon name="checkCircle" size={16} /> 확인함
            </span>
          )}
          {d.exclude && (
            <input
              className="input"
              aria-label={`${blockLabel(b)} 제외 사유`}
              placeholder={isReview ? '제외 사유 (필수)' : '제외 사유 (선택)'}
              value={d.reason}
              aria-invalid={reasonMissing}
              onChange={(e) => decide(b.block_id, { reason: e.target.value })}
            />
          )}
        </div>
      )
    },
  }

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={`추출 확인 · ${label}`}
        title={
          <>
            확인할 <strong>원문 {blocks ? toCheck.length : ''}건</strong>
          </>
        }
        lead="원문은 고치지 않아요. 읽은 내용이 맞는지 확인하거나 제외만 합니다."
      />
      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={reload}>다시 불러오기</Button>} />
      ) : !blocks ? (
        <Loading text="문서에서 읽은 원문을 불러오는 중이에요" />
      ) : (
        <>
          <div className="row muted" style={{ fontSize: 15 }}>
            전체 {blocks.length}건 · 실패 {failCount}건 · 확인 필요 {reviewCount}건 · 정상 {passed.length}건
          </div>
          {notice && <Notice kind="warning" title={notice} />}
          {sheets.length > 0 && <Notice title={`요구사항을 읽지 않은 시트가 있어요: ${sheets.join(', ')}`} />}

          <DataTable
            label="확인할 원문"
            rows={toCheck}
            rowKey={(b) => b.block_id}
            columns={[...baseColumns, decisionColumn]}
            minWidth={960}
            empty="확인할 원문이 없어요."
          />

          {passed.length > 0 && (
            <details className="more card card--soft" style={{ padding: '14px 18px' }}>
              <summary>정상 {passed.length}건 보기</summary>
              <div style={{ marginTop: 12 }}>
                <DataTable label="정상 원문" rows={passed} rowKey={(b) => b.block_id} columns={baseColumns} pageSize={20} minWidth={720} />
              </div>
            </details>
          )}

          {warnings.length > 0 && (
            <Notice kind="warning" title="제외하는 원문을 관련 요구사항으로 적은 원문이 있어요">
              <ul>
                {warnings.map((w) => (
                  <li key={w.block_id}>
                    {blockName(w.block_id)}를 제외해도 {w.related_block_ids.map(blockName).join(', ')}의 관련 요구사항에는 남아요. 제외는 할 수 있어요.
                  </li>
                ))}
              </ul>
            </Notice>
          )}
          {blocking.length > 0 && (
            <Notice title="보내기 전에 확인할 것">
              <ul>
                {blocking.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Notice>
          )}
          {actionError && <Notice kind="error" title={actionError} />}

          <div className="row row--between">
            <span className="muted">
              {decided} / {toCheck.length} 확인
            </span>
            <div className="row">
              <ConfirmButton
                variant="danger"
                disabled={sending || !canAnswer}
                title="실행을 중단할까요?"
                description="이 실행은 취소되고 되돌릴 수 없어요."
                okText="전체 중단"
                cancelText="계속 확인"
                danger
                onConfirm={() => send(STOP_RESPONSE)}
              >
                전체 중단
              </ConfirmButton>
              <Button
                variant={allDecided && blocking.length === 0 ? 'accent' : 'primary'}
                size="lg"
                loading={sending}
                loadingText="보내는 중"
                disabled={blocking.length > 0 || !canAnswer}
                onClick={() => send(buildResponse(blocks, decisions))}
                iconEnd={<Icon name="arrowRight" size={18} />}
              >
                확인하고 분석 시작
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default ExtractionPanel
