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
import Segmented from '../../ui/Segmented.tsx'
import { useResume } from '../run/useResume.ts'
import {
  ACTION_LABEL,
  buildResponse,
  changedCount,
  initialAnswers,
  needsAttention,
  problems,
  sortRequirements,
  splitFromSameSource,
  switchAction,
  typeText,
  type Action,
  type Answer,
  type Answers,
} from './rules.ts'

// UI-03 분석 확인 (docs/09). 요구사항마다 유지·수정·분할을 고른다. 답하지 않은 요구사항은 유지로 본다.
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
  const [answers, setAnswers] = useState<Answers>({})
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
        setAnswers(initialAnswers(items))
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
  const blocking = problems(answers)
  const changed = changedCount(answers)
  const setAnswer = (reqId: string, answer: Answer) => setAnswers((prev) => ({ ...prev, [reqId]: answer }))

  const columns: Column<AnalysedRequirement>[] = [
    {
      key: 'id',
      title: 'ID',
      width: 110,
      render: (r) => (
        <div className="stack-sm" style={{ gap: 2 }}>
          <span className="mono">{r.id}</span>
          <span className="subtle" style={{ fontSize: 12 }}>
            원문 {r.source_id ?? '—'}
          </span>
        </div>
      ),
    },
    {
      key: 'text',
      title: '요구사항',
      render: (r) => (
        <div className="stack-sm" style={{ gap: 4 }}>
          <span>{r.text}</span>
          {split.has(r.id) && (
            <span className="subtle" style={{ fontSize: 13 }}>
              같은 원문에서 자동 분할됐어요. 의미가 유지됐으면 그대로 진행하세요.
            </span>
          )}
          {r.source_text && r.source_text !== r.text && (
            <span className="subtle" style={{ fontSize: 13 }}>
              원문: {r.source_text}
            </span>
          )}
        </div>
      ),
    },
    { key: 'type', title: '유형', width: 130, render: (r) => typeText(r) },
    {
      key: 'issues',
      title: '품질 경고 · 질문',
      width: 240,
      render: (r) =>
        r.quality_issues.length === 0 ? (
          <span className="subtle">{split.has(r.id) ? '자동 분할됨 · 진행 가능' : '경고 없음'}</span>
        ) : (
          <div className="stack-sm">
            {r.quality_issues.map((issue, i) => (
              <div key={i}>
                <StatusTag tone="warning">경고</StatusTag> {issue.message}
                {issue.question && <div className="muted" style={{ marginTop: 4 }}>질문: {issue.question}</div>}
              </div>
            ))}
          </div>
        ),
    },
    {
      key: 'answer',
      title: '답',
      width: 290,
      render: (r) => {
        const a = answers[r.id] ?? { action: 'keep', texts: [] }
        return (
          <div className="stack-sm">
            <Segmented<Action>
              variant="choice"
              label={`${r.id} 답`}
              value={a.action}
              onChange={(v) => setAnswer(r.id, switchAction(r, v))}
              options={(['keep', 'edit', 'split'] as const).map((v) => ({ value: v, label: ACTION_LABEL[v] }))}
            />
            {a.action !== 'keep' &&
              a.texts.map((text, i) => (
                <div key={i} className="row" style={{ gap: 6, alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                  <textarea
                    className="textarea"
                    rows={2}
                    aria-label={`${r.id} ${a.action === 'edit' ? '수정 문장' : `분할 문장 ${i + 1}`}`}
                    aria-invalid={!text.trim()}
                    value={text}
                    placeholder={a.action === 'split' ? `조각 ${i + 1}` : '바꿀 문장'}
                    onChange={(e) => setAnswer(r.id, { ...a, texts: a.texts.map((t, j) => (j === i ? e.target.value : t)) })}
                  />
                  {a.action === 'split' && a.texts.length > 2 && (
                    <Button
                      variant="secondary"
                      size="sm"
                      aria-label={`${r.id} 조각 ${i + 1} 지우기`}
                      onClick={() => setAnswer(r.id, { ...a, texts: a.texts.filter((_, j) => j !== i) })}
                    >
                      빼기
                    </Button>
                  )}
                </div>
              ))}
            {a.action === 'split' && (
              <div className="stack-sm" style={{ gap: 4 }}>
                <Button variant="secondary" size="sm" icon={<Icon name="plus" size={14} />} onClick={() => setAnswer(r.id, { ...a, texts: [...a.texts, ''] })}>
                  조각 더하기
                </Button>
                <span className="subtle" style={{ fontSize: 13 }}>
                  첫 조각은 {r.id}, 나머지는 서버가 새 ID를 붙여요.
                </span>
              </div>
            )}
            {a.action === 'edit' && r.quality_issues.some((q) => q.question) && (
              <span className="subtle" style={{ fontSize: 13 }}>질문의 답을 문장에 넣어 고쳐 주세요.</span>
            )}
          </div>
        )
      },
    },
  ]

  return (
    <div className="stack">
      <ScreenHead
        eyebrow={<RunEyebrow screen="분석 확인" label={label} run={run} />}
        title={
          <>
            확인할 <strong>요구사항 {reqs ? toCheck.length : ''}건</strong>
          </>
        }
        lead="문서에서 뽑은 요구사항을 확인해요. 고칠 것이 없으면 그대로 두면 돼요(유지)."
      />
      {loadError ? (
        <Notice kind="error" title={errorMessage(loadError)} action={<Button variant="secondary" size="sm" onClick={reload}>다시 불러오기</Button>} />
      ) : !reqs ? (
        <Loading text="정리한 요구사항을 불러오는 중이에요" />
      ) : (
        <>
          <div className="muted" style={{ fontSize: 15 }}>
            요구사항 {reqs.length}건 · 확인할 것 {toCheck.length}건 · 바꾼 것 {changed}건
          </div>
          {notice && <Notice kind="warning" title={notice} />}
          <section aria-label="품질 경고·질문" className="stack-sm">
            <h2 className="section-title" style={{ margin: 0 }}>
              품질 경고 · 질문 {toCheck.length}건
            </h2>
            <DataTable label="품질 경고·질문" rows={toCheck} rowKey={(r) => r.id} columns={columns} minWidth={1000} empty="품질 경고·질문이 없어요." />
          </section>
          {splitOnly.length > 0 && (
            <section aria-label="자동 분할 결과" className="stack-sm">
              <h2 className="section-title" style={{ margin: 0 }}>
                자동 분할 결과 {splitOnly.length}건 · 진행 가능
              </h2>
              <p className="muted" style={{ margin: 0 }}>
                분할 자체는 오류가 아니에요. 원문의 조건·대상이 유지됐으면 ‘유지’로 진행하세요.
              </p>
              <DataTable label="자동 분할 결과" rows={splitOnly} rowKey={(r) => r.id} columns={columns} minWidth={1000} />
            </section>
          )}
          {others.length > 0 && (
            <details className="more card card--soft" style={{ padding: '14px 18px' }}>
              <summary>문제가 없는 요구사항 {others.length}건 (바꿀 때만 펼치세요)</summary>
              <div style={{ marginTop: 12 }}>
                <DataTable label="문제가 없는 요구사항" rows={others} rowKey={(r) => r.id} columns={columns} pageSize={20} minWidth={1000} />
              </div>
            </details>
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
          {error && <Notice kind="error" title={error} />}
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <Button
              size="lg"
              variant={blocking.length === 0 ? 'accent' : 'primary'}
              loading={sending}
              loadingText="보내는 중"
              disabled={blocking.length > 0 || !canAnswer}
              onClick={() => send(buildResponse(answers))}
              iconEnd={<Icon name="arrowRight" size={18} />}
            >
              {changed > 0 ? `${changed}건 바꾸고 설계 시작` : '그대로 설계 시작'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

export default RequirementsPanel
