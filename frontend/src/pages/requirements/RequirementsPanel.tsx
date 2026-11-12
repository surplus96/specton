import RunEyebrow from '../run/RunEyebrow.tsx'
import { useEffect, useMemo, useState } from 'react'
import { getView } from '../../api/client.ts'
import { errorMessage } from '../../api/errors.ts'
import type { RunStatus } from '../../api/types.ts'
import type { AnalysedRequirement } from '../../api/viewItems.ts'
import Icon from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import Button from '../../ui/Button.tsx'
import DataTable, { type Column } from '../../ui/DataTable.tsx'
import Loading from '../../ui/Loading.tsx'
import Notice from '../../ui/Notice.tsx'
import ScreenHead from '../../ui/ScreenHead.tsx'
import { useResume } from '../run/useResume.ts'
import { needsAttention, sortRequirements, splitFromSameSource, typeText } from './rules.ts'

// UI-03 분석 확인 (docs/09). 보기 전용: 요구사항을 보여 주고, 버튼 하나로 모두 유지(빈 answers)로 보내 설계를 시작한다.
// 수정·분할 입력은 쓰지 않는다. 서버 계약(빈 answers = 모두 keep)은 그대로다.
// 품질 경고·질문이 있거나 같은 원문에서 나뉜 요구사항을 먼저 보인다. 질문을 「자동으로 고쳤다」고 표시하지 않는다.
type Props = {
  run: RunStatus
  onChanged: () => Promise<void>
  label: string
}

function RequirementsPanel({ run, onChanged, label }: Props) {
  const interruptId = run.interrupt?.interrupt_id
  const [reqs, setReqs] = useState<AnalysedRequirement[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const { send, sending, error, notice, reloadKey, reload, canAnswer } = useResume(run, onChanged)

  useEffect(() => {
    let alive = true
    setReqs(null)
    setLoadError(null)
    getView(run.run_id, 'requirements', run.revision)
      .then((view) => {
        if (!alive) return
        const items = view.items as AnalysedRequirement[]
        setReqs(items)
      })
      .catch((err: unknown) => alive && setLoadError(err))
    return () => {
      alive = false
    }
  }, [run.run_id, run.revision, interruptId, reloadKey])

  const split = useMemo(() => splitFromSameSource(reqs ?? []), [reqs])
  const sorted = useMemo(() => sortRequirements(reqs ?? []), [reqs])
  // 품질 경고·질문이 있는 것만 「확인할 것」. 경고 없이 자동 분할만 된 것은 따로 보이고 그대로 진행해도 된다 (#331)
  const toCheck = sorted.filter((r) => r.quality_issues.length > 0)
  const splitOnly = sorted.filter((r) => r.quality_issues.length === 0 && split.has(r.id))
  const others = sorted.filter((r) => !needsAttention(r, split))

  const columns: Column<AnalysedRequirement>[] = [
    {
      key: 'id',
      title: '원문',
      width: 110,
      render: (r) => (
        <div className="stack-sm" style={{ gap: 2 }}>
          <span className="mono">{r.source_id ?? '—'}</span>
          <span className="subtle mono" style={{ fontSize: 12 }}>
            {r.id}
          </span>
        </div>
      ),
    },
    {
      key: 'text',
      title: '요구사항 요약',
      render: (r) => <p className="requirement-preview">{r.text}</p>,
    },
    { key: 'type', title: '유형', width: 110, render: (r) => typeText(r) },
    {
      key: 'issues',
      title: 'AI가 물어본 것',
      width: 180,
      render: (r) => r.quality_issues.length === 0
        ? <span className="subtle">{split.has(r.id) ? '자동 분할됨 · 진행 가능' : '경고 없음'}</span>
        : <div className="stack-sm">
            <StatusTag tone="warning">경고 {r.quality_issues.length}건 · 질문 {r.quality_issues.filter((q) => q.question).length}건</StatusTag>
            <span className="subtle">상세 보기에서 확인</span>
          </div>,
    },
  ]

  const details = (req: AnalysedRequirement) => (
    <section className="requirement-details stack-sm" aria-label={`${req.source_id ?? req.id} 상세`}>
      <h3 className="h3">요구사항 전체</h3>
      <p className="requirement-detail-text">{req.text}</p>
      {split.has(req.id) && <Notice title="같은 원문에서 자동 분할된 요구사항입니다." />}
      {req.source_text && req.source_text !== req.text && <div className="stack-sm"><h3 className="h3">원문 전체</h3><p className="requirement-detail-text">{req.source_text}</p></div>}
      {req.quality_issues.length > 0 && <div className="stack-sm"><h3 className="h3">AI가 물어본 것</h3>
        {req.quality_issues.map((issue, i) => <div key={i} className="stack-sm"><strong className="requirement-detail-text">{issue.message}</strong>{issue.question && <p className="requirement-detail-text">확인 질문: {issue.question}</p>}</div>)}
      </div>}
    </section>
  )
  const detailLabel = (req: AnalysedRequirement, opened: boolean) => `${req.source_id ?? req.id} ${opened ? '상세 접기' : '상세 보기'}`

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="요구사항 확인" label={label} run={run} />}
        title={
          <>
            정리한 <strong>요구사항 {reqs ? reqs.length : ''}건</strong>
          </>
        }
        lead="문서에서 뽑은 요구사항이에요. 살펴본 뒤 설계를 시작하세요."
      />
      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={reload}>다시 불러오기</Button>} />
      ) : !reqs ? (
        <Loading text="정리한 요구사항을 불러오는 중이에요" />
      ) : (
        <>
          <div className="muted" style={{ fontSize: 15 }}>
            요구사항 {reqs.length}건 · AI가 물어본 것 {toCheck.length}건
          </div>
          {notice && <Notice kind="warning" title={notice} />}
          <section aria-label="품질 경고·질문" className="stack-sm">
            <h2 className="section-title" style={{ margin: 0 }}>
              AI가 물어본 것 {toCheck.length}건
            </h2>
            <DataTable label="품질 경고·질문" rows={toCheck} rowKey={(r) => r.id} columns={columns} expand={details} expandLabel={detailLabel} expandText="상세 보기" minWidth={1000} empty="품질 경고·질문이 없어요." />
          </section>
          {splitOnly.length > 0 && (
            <section aria-label="자동 분할 결과" className="stack-sm">
              <h2 className="section-title" style={{ margin: 0 }}>
                자동 분할 결과 {splitOnly.length}건 · 진행 가능
              </h2>
              <p className="muted" style={{ margin: 0 }}>
                분할 자체는 오류가 아니에요.
              </p>
              <DataTable label="자동 분할 결과" rows={splitOnly} rowKey={(r) => r.id} columns={columns} expand={details} expandLabel={detailLabel} expandText="상세 보기" minWidth={1000} />
            </section>
          )}
          {others.length > 0 && (
            <details className="more card card--soft" style={{ padding: '14px 18px' }}>
              <summary>문제가 없는 요구사항 {others.length}건</summary>
              <div style={{ marginTop: 12 }}>
                <DataTable label="문제가 없는 요구사항" rows={others} rowKey={(r) => r.id} columns={columns} expand={details} expandLabel={detailLabel} expandText="상세 보기" pageSize={20} minWidth={1000} />
              </div>
            </details>
          )}
          {error && <Notice kind="error" title={error} />}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <Button
              size="lg"
              variant="accent"
              loading={sending}
              loadingText="보내는 중"
              disabled={!canAnswer}
              onClick={() => send({ kind: 'requirements', answers: [] })}
              iconEnd={<Icon name="arrowRight" size={18} />}
            >
              설계 시작
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

export default RequirementsPanel
