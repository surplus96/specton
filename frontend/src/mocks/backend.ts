// mock 서버: 백엔드 없이 화면을 만들 수 있게 API를 흉내 낸다 (개발용, 배포에는 들어가지 않음).
// 규칙은 docs/06-api.md를 따르고, 응답 모양은 schema.d.ts(계약에서 자동 생성) 타입으로 검사한다.
//
// 실행 흐름 (시간이 지나면 저절로 다음 상태로 간다)
//   queued → parsing → awaiting_input(UI-02)
//     ─답→ analysing → awaiting_requirements(UI-03)
//     ─답→ designing → generating → reviewing → awaiting_review(UI-06)
//     ─승인→ exporting → completed   ─수정 요청→ revision+1, designing부터 다시
//
// 파일 이름에 아래 낱말을 넣으면 다른 흐름을 볼 수 있다.
//   quick        확인할 것이 없어 UI-02·UI-03을 건너뜀 (ADR-0015)
//   slow-queue   한동안 queued로 기다림 (동시 실행 한도)
//   fail         분석 중 모델 호출 실패 (LLM_UNAVAILABLE)
//   unreadable   문서를 읽지 못함 (EXTRACTION_FAILED + 자세히 보기 문장)
//   conflict     첫 확인 답이 409 INTERRUPT_STALE (다른 탭에서 먼저 답한 상황)
//   no-questions 추출 확인은 멈추고, 분석 확인은 확인할 것이 없어 건너뜀 (ADR-0015)
//   critical     최종 검토에 차단 오류(critical)가 있어 승인 불가. 수정 요청 한 번 뒤에 사라진다
//   partial-review 최종 검토에서 일부 검토 관점이 빠짐(failed_branches)·자동 재작업을 멈춘 이유(hitl_reason)
//   erd-attack   (다른 낱말과 함께) ERD 원문에 지시문을 넣어 돌려줌. 웹이 그리지 않는지 보는 보안 시험 (#190)
//   large        (다른 낱말과 함께) 설계를 엔티티 50개·관계 60개로 돌려줌. AI Workspace 성능 확인 (#281)
import { delay, http, HttpResponse } from 'msw'
import { mockRtmCsv } from './rtm.ts'
import type { AnalysedRequirement, DesignItem, ExtractionBlock } from '../api/viewItems.ts'
import type {
  ApiErrorBody,
  ErrorCode,
  ExtractionResponse,
  Interrupt,
  InterruptKind,
  RequirementsResponse,
  ResumeRequest,
  RunState,
  RunStatus,
  RunSummary,
  RunView,
  SseEvent,
  SseEventName,
  ViewSection,
} from '../api/types.ts'
import {
  ARTIFACT_FORMATS,
  designItems,
  LARGE_DESIGN_ITEMS,
  DDL_SAMPLE,
  ERD_ATTACK_SAMPLE,
  ERD_SAMPLE,
  extractionItems,
  CRITICAL_FINDING,
  findingItems,
  requirementItems,
} from './data.ts'

export type MockOptions = {
  /** 한 단계가 지나가는 시간(ms). 테스트에서는 0으로 두면 바로 다음 확인 화면까지 간다. */
  stepMs?: number
  /** 실행 중 취소가 끝나기까지 걸리는 시간(ms). 실제로는 최대 2분 (ADR-0012) */
  cancelMs?: number
  /** 현재 시각. 테스트에서 시간을 조절할 때 바꾼다. */
  now?: () => number
  /** SSE 스트림이 새 이벤트를 확인하는 간격(ms). 백엔드 SPECTON_SSE_POLL_SECONDS에 해당 */
  pollMs?: number
}

type Item = Record<string, unknown>

type Step = {
  status: RunState
  stage: string | null
  ms?: number // 이 단계로 넘어가기까지 기다리는 시간. 없으면 stepMs
  interrupt?: InterruptKind
  error?: { code: ErrorCode; message: string; detail?: string }
  message?: string // SSE status 이벤트 문구를 바꿀 때
  payload?: Item // SSE status 이벤트 payload (건너뛴 시트 안내 등)
  nextRevision?: boolean
}

type MockRun = {
  run_id: string
  pack: string
  fileName: string
  created_at: string
  scenario: 'normal' | 'quick' | 'slow-queue' | 'fail' | 'unreadable' | 'conflict' | 'no-questions' | 'critical' | 'partial-review'
  conflictPending: boolean // conflict: 다음 답을 409로 돌려준다
  erdAttack: boolean // erd-attack: ERD 원문에 지시문을 넣어 돌려준다 (웹 보안 시험, #190)
  large: boolean // large: 엔티티 50개 설계를 돌려준다 (AI Workspace 성능 확인, #281)
  status: RunState
  revision: number
  stage: string | null
  interrupt: Interrupt | null
  error: ApiErrorBody | null
  plan: Step[]
  since: number
  events: SseEvent[]
  sections: Set<ViewSection> // 이미 결과가 있는 view section
  artifactRevisions: Set<number> // 산출물을 만든 revision
  approvedRevisions: Set<number> // 승인한 revision (PDF는 여기서만)
  extraction: Item[]
  requirements: Item[]
  findings: Item[] // 지금 revision의 검토 지적
}

// 백엔드 runner.py와 같은 문구
const STATUS_MESSAGES: Partial<Record<RunState, string>> = {
  parsing: '문서를 읽고 있습니다',
  awaiting_input: '추출 결과 확인을 기다립니다',
  analysing: '요구사항을 분석하고 있습니다',
  awaiting_requirements: '요구사항 확인을 기다립니다',
  designing: '설계 모델을 만들고 있습니다',
  generating: '산출물을 만들고 있습니다',
  reviewing: '설계를 검토하고 있습니다',
  awaiting_review: '최종 검토를 기다립니다',
  exporting: '산출물을 내보내고 있습니다',
  completed: '설계를 완료했습니다',
  cancel_requested: '취소를 요청했습니다',
  cancelled: '실행을 취소했습니다',
}
const INTERRUPT_MESSAGES: Record<InterruptKind, string> = {
  extraction: '추출 결과 확인이 필요합니다',
  requirements: '요구사항 확인이 필요합니다',
  review: '최종 검토가 필요합니다',
}
const SKIPPED_REQUIREMENTS_CHECK = '확인할 항목이 없어 분석 확인을 생략했습니다'
const MAX_UPLOAD_MB = 20
const PACKS = ['inventory', 'maintenance']
const ACCEPTED_FORMATS = ['xlsx', 'csv', 'hwpx', 'hwp']
const STALE_MESSAGE = '이미 답했거나 지금 기다리는 확인 요청이 아닙니다. 최신 상태를 조회하세요.'
const REVISION_MESSAGE = '다른 revision입니다. 최신 상태를 조회한 뒤 다시 시도하세요.'
const STATE_MESSAGE = '지금 상태에서는 할 수 없는 요청입니다. 최신 상태를 조회하세요.'

const FINISHED: RunState[] = ['completed', 'failed', 'cancelled']
const WAITING: RunState[] = ['queued', 'awaiting_input', 'awaiting_requirements', 'awaiting_review']

/** 오류 응답을 보내기 위해 던지는 값 */
class Reject {
  readonly status: number
  readonly body: ApiErrorBody
  constructor(status: number, code: ErrorCode, message: string, runId: string | null = null) {
    this.status = status
    this.body = { code, message, run_id: runId, retryable: false }
  }
}

export function createMockBackend(options: MockOptions = {}) {
  const stepMs = options.stepMs ?? 1500
  const cancelMs = options.cancelMs ?? 4000
  const now = options.now ?? Date.now
  const pollMs = options.pollMs ?? 250
  const runs = new Map<string, MockRun>()

  // ── 상태 흐름 ─────────────────────────────────────────

  function pushEvent(run: MockRun, event: SseEventName, message: string, payload?: Item) {
    run.events.push({
      id: run.events.length + 1,
      event,
      data: { run_id: run.run_id, revision: run.revision, stage: run.stage, message, payload },
    })
  }

  function apply(run: MockRun, step: Step) {
    if (step.nextRevision) run.revision += 1
    run.status = step.status
    run.stage = step.stage
    run.interrupt = null

    // 지나간 단계의 결과를 화면에서 볼 수 있게 한다
    if (step.status !== 'parsing' && step.status !== 'queued') run.sections.add('extraction')
    if (['awaiting_requirements', 'designing'].includes(step.status)) run.sections.add('requirements')
    if (step.status === 'generating') run.sections.add('design')
    if (step.status === 'reviewing') run.artifactRevisions.add(run.revision)
    if (step.status === 'awaiting_review') run.sections.add('review')

    if (step.interrupt) {
      const interruptId = `int-${run.revision}-${run.events.length + 1}`
      run.interrupt = {
        interrupt_id: interruptId,
        kind: step.interrupt,
        message: INTERRUPT_MESSAGES[step.interrupt],
      }
      const payload: Item = { interrupt_id: interruptId, kind: step.interrupt }
      if (step.interrupt === 'review') {
        // 불완전 검토 안내 (docs/06 SSE interrupt payload)
        payload.failed_branches = run.scenario === 'partial-review' ? ['A07'] : []
        if (run.scenario === 'partial-review') payload.hitl_reason = 'rework_limit'
      }
      pushEvent(run, 'interrupt', run.interrupt.message, payload)
    } else if (step.error) {
      // 서버처럼 상태 조회 error.detail과 SSE payload.detail에 같은 값을 넣는다 (#204·#230, docs/06)
      run.error = {
        code: step.error.code,
        message: step.error.message,
        run_id: run.run_id,
        retryable: step.error.code === 'LLM_UNAVAILABLE',
        detail: step.error.detail ?? null,
      }
      const payload: Item = { code: step.error.code, retryable: run.error.retryable }
      if (step.error.detail) payload.detail = step.error.detail
      pushEvent(run, 'error', step.error.message, payload)
    } else if (step.status === 'completed') {
      run.approvedRevisions.add(run.revision)
      pushEvent(run, 'completed', STATUS_MESSAGES.completed!)
    } else if (step.status === 'cancelled') {
      pushEvent(run, 'cancelled', STATUS_MESSAGES.cancelled!)
    } else {
      pushEvent(run, 'status', step.message ?? STATUS_MESSAGES[step.status] ?? step.status, step.payload)
    }
  }

  /** 시간이 지난 만큼 계획된 단계를 진행한다. 응답하기 전에 항상 부른다. */
  function advance(run: MockRun) {
    const t = now()
    while (run.plan.length > 0) {
      const next = run.plan[0]
      const due = run.since + (next.ms ?? stepMs)
      if (t < due) break
      run.plan.shift()
      run.since = due
      apply(run, next)
    }
  }

  /** 지금 바로 상태를 바꾸고(202 응답에 반영), 이어질 단계를 계획한다 */
  function moveTo(run: MockRun, step: Step, plan: Step[]) {
    apply(run, step)
    run.since = now()
    run.plan = plan
  }

  const toReview: Step[] = [
    { status: 'generating', stage: 'generating' },
    { status: 'reviewing', stage: 'reviewing' },
    { status: 'awaiting_review', stage: 'review', interrupt: 'review' },
  ]

  function planAfterUpload(scenario: MockRun['scenario']): Step[] {
    const parsing: Step = { status: 'parsing', stage: 'parsing' }
    switch (scenario) {
      case 'unreadable':
        return [
          parsing,
          {
            status: 'failed',
            stage: 'parsing',
            error: {
              code: 'EXTRACTION_FAILED',
              message: '요구사항 표를 찾지 못했어요. 표의 칸 이름을 확인해 주세요.',
              detail:
                '위쪽 20행 안에 「요구사항 ID」와 「요구사항명」 또는 「상세 내용」 칸이 있어야 해요. 이 파일에서 찾은 칸 이름: 번호, 내용.',
            },
          },
        ]
      case 'quick':
        return [
          parsing,
          { status: 'analysing', stage: 'analysing', nextRevision: true },
          { status: 'designing', stage: 'designing', message: SKIPPED_REQUIREMENTS_CHECK },
          ...toReview,
        ]
      case 'slow-queue':
        return [
          { status: 'queued', stage: null, ms: stepMs * 3, message: '다른 실행이 끝나기를 기다립니다' },
          parsing,
          { status: 'awaiting_input', stage: 'parsing', interrupt: 'extraction' },
        ]
      default:
        return [
          parsing,
          // 엑셀에서 요구사항 표가 없는 시트는 정보 한 줄로 알린다 (docs/06 SSE). 확인을 멈추게 하지는 않는다
          {
            status: 'parsing',
            stage: 'parsing',
            ms: 0,
            message: '요구사항을 읽지 않은 시트가 있습니다',
            payload: { info: 'skipped_sheets', document_id: 'doc-1', sheets: ['표지', '개정이력'] },
          },
          { status: 'awaiting_input', stage: 'parsing', interrupt: 'extraction' },
        ]
    }
  }

  // ── 요청 처리 ─────────────────────────────────────────

  function findRun(id: string): MockRun {
    const run = runs.get(id)
    if (!run) throw new Reject(404, 'RUN_NOT_FOUND', '실행을 찾을 수 없습니다.')
    advance(run)
    return run
  }

  function statusOf(run: MockRun): RunStatus {
    return {
      run_id: run.run_id,
      status: run.status,
      revision: run.revision,
      stage: run.stage,
      interrupt: run.interrupt,
      error: run.error,
    }
  }

  function createRun(file: File | null, pack: string | null): RunStatus {
    if (!file || !pack) throw new Reject(422, 'INVALID_REQUEST', '파일과 팩을 함께 보내 주세요.')
    const suffix = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
    if (!ACCEPTED_FORMATS.includes(suffix)) {
      throw new Reject(415, 'UNSUPPORTED_MEDIA_TYPE', `지원하는 형식은 ${ACCEPTED_FORMATS.map((f) => `.${f}`).join(', ')}입니다.`)
    }
    if (!PACKS.includes(pack)) throw new Reject(422, 'PACK_UNSUPPORTED', `지원하는 팩은 ${PACKS.join(', ')}입니다.`)
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      throw new Reject(413, 'UPLOAD_TOO_LARGE', `파일이 ${MAX_UPLOAD_MB}MB를 넘습니다.`)
    }
    if (file.size === 0) throw new Reject(422, 'INVALID_REQUEST', '빈 파일입니다.')

    const name = file.name.toLowerCase()
    const scenario: MockRun['scenario'] = name.includes('unreadable')
      ? 'unreadable'
      : name.includes('slow-queue')
        ? 'slow-queue'
        : name.includes('quick')
          ? 'quick'
          : name.includes('fail')
            ? 'fail'
            : name.includes('conflict')
              ? 'conflict'
              : name.includes('no-questions')
                ? 'no-questions'
                : name.includes('critical')
                  ? 'critical'
                  : name.includes('partial-review')
                    ? 'partial-review'
                    : 'normal'

    const run: MockRun = {
      run_id: crypto.randomUUID(),
      pack,
      fileName: file.name,
      created_at: new Date(now()).toISOString(),
      scenario,
      conflictPending: scenario === 'conflict',
      erdAttack: name.includes('erd-attack'),
      large: name.includes('large'),
      status: 'queued',
      revision: 0,
      stage: null,
      interrupt: null,
      error: null,
      plan: planAfterUpload(scenario),
      since: now(),
      events: [],
      sections: new Set(),
      artifactRevisions: new Set(),
      approvedRevisions: new Set(),
      extraction: structuredClone(extractionItems),
      requirements: structuredClone(requirementItems),
      findings: structuredClone(scenario === 'critical' ? [CRITICAL_FINDING, ...findingItems] : findingItems),
    }
    runs.set(run.run_id, run)
    pushEvent(run, 'status', '실행을 접수했습니다')
    return statusOf(run)
  }

  function listRuns(url: URL): RunSummary[] {
    const status = url.searchParams.get('status')
    const limitText = url.searchParams.get('limit')
    const limit = limitText === null ? 20 : Number(limitText)
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      throw new Reject(422, 'INVALID_REQUEST', 'limit는 1~100입니다.')
    }
    return [...runs.values()]
      .map((run) => (advance(run), run))
      .filter((run) => !status || run.status === status)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, limit)
      .map((run) => ({ run_id: run.run_id, status: run.status, revision: run.revision, created_at: run.created_at }))
  }

  function view(run: MockRun, url: URL): RunView {
    const section = url.searchParams.get('section') as ViewSection | null
    if (!section || !['extraction', 'requirements', 'design', 'review'].includes(section)) {
      throw new Reject(422, 'INVALID_REQUEST', 'section은 extraction, requirements, design, review 중 하나입니다.')
    }
    const revisionText = url.searchParams.get('revision')
    const revision = revisionText === null ? run.revision : Number(revisionText)
    if (revision > run.revision) throw new Reject(409, 'RUN_REVISION_CONFLICT', REVISION_MESSAGE, run.run_id)

    const source: Record<ViewSection, Item[]> = {
      extraction: run.extraction,
      requirements: run.requirements,
      design: run.large ? LARGE_DESIGN_ITEMS : designItems,
      review: run.findings,
    }
    const items = run.sections.has(section) ? source[section] : []
    const artifacts = run.artifactRevisions.has(revision)
      ? Object.entries(ARTIFACT_FORMATS).filter(([kind]) => kind !== 'review' && (kind !== 'manifest' || run.approvedRevisions.has(revision))).flatMap(([kind, formats]) =>
          formats
            // 서버처럼 ERD PDF는 승인 전에도 비공개 후보(approved=false)로 목록에 있다. 받으면 409 (docs/06, #217).
            // 기능 명세 PDF 연결은 후속 범위라 승인 뒤에만 넣는다.
            .filter((f) => f !== 'pdf' || kind === 'erd' || run.approvedRevisions.has(revision))
            .map((file_format) => ({
              kind,
              file_format,
              revision,
              hash: `mock-${kind}-${revision}`,
              approved: run.approvedRevisions.has(revision),
              ...(kind === 'ddl' ? { validation: { status: 'passed', validated_at: '2026-11-10T00:00:00Z' } } : {}),
            })),
        )
      : []
    return { run_id: run.run_id, revision, section, items, artifacts }
  }

  function resume(run: MockRun, body: ResumeRequest): RunStatus {
    if (!run.interrupt || body.interrupt_id !== run.interrupt.interrupt_id) {
      throw new Reject(409, 'INTERRUPT_STALE', STALE_MESSAGE, run.run_id)
    }
    if (run.conflictPending) {
      // 다른 탭에서 먼저 답해 확인 요청이 새로 나온 상황을 흉내 낸다. 화면은 상태를 다시 읽고 다시 고른다
      run.conflictPending = false
      const kind = run.interrupt.kind
      apply(run, { status: run.status, stage: run.stage, interrupt: kind })
      throw new Reject(409, 'INTERRUPT_STALE', STALE_MESSAGE, run.run_id)
    }
    if (body.expected_revision !== run.revision) {
      throw new Reject(409, 'RUN_REVISION_CONFLICT', REVISION_MESSAGE, run.run_id)
    }
    const answer = body.response
    if (answer.kind !== run.interrupt.kind) {
      throw new Reject(422, 'INVALID_RESPONSE', '확인 요청과 응답 종류가 다릅니다.', run.run_id)
    }
    const invalid = (message: string) => new Reject(422, 'INVALID_RESPONSE', message, run.run_id)

    if (answer.kind === 'extraction') {
      checkExtraction(run, answer, invalid)
      if (!answer.confirmed) {
        moveTo(run, { status: 'cancelled', stage: run.stage }, [])
        return statusOf(run)
      }
      const excluded = new Map((answer.excluded_blocks ?? []).map((b) => [b.block_id, b.reason ?? null]))
      for (const block of run.extraction) {
        const id = block.block_id as string
        if (excluded.has(id)) {
          block.user_decision = 'excluded'
          block.excluded_reason = excluded.get(id)
        } else if (block.extraction_status === 'review') {
          block.user_decision = 'confirmed'
        }
      }
      const analysing: Step = { status: 'analysing', stage: 'analysing', nextRevision: true }
      const warnings = relatedWarningsOf(run.extraction)
      if (run.scenario === 'fail') {
        moveTo(run, analysing, [
          {
            status: 'failed',
            stage: 'analysing',
            error: { code: 'LLM_UNAVAILABLE', message: '모델을 호출하지 못했습니다. 잠시 후 다시 시도해 주세요.' },
          },
        ])
      } else if (run.scenario === 'no-questions') {
        moveTo(run, analysing, [
          { status: 'designing', stage: 'designing', message: SKIPPED_REQUIREMENTS_CHECK },
          ...toReview,
        ])
      } else {
        moveTo(run, analysing, [
          { status: 'awaiting_requirements', stage: 'analysing', interrupt: 'requirements' },
        ])
      }
      // 백엔드(graph.py _related_warnings)처럼 경고만 남기고 제외는 막지 않는다
      for (const payload of warnings) {
        pushEvent(run, 'status', '제외한 원문을 관련 요구사항으로 적은 원문이 있습니다', payload)
      }
      return statusOf(run)
    }

    if (answer.kind === 'requirements') {
      applyRequirements(run, answer, invalid)
      moveTo(run, { status: 'designing', stage: 'designing' }, [...toReview])
      return statusOf(run)
    }

    // review
    if (answer.decision === 'hold') {
      // 같은 확인 요청으로 계속 기다린다. 상태 이벤트만 남긴다 (docs/06).
      pushEvent(run, 'status', '최종 검토를 보류했습니다')
      return statusOf(run)
    }
    if (answer.decision === 'revise') {
      // 수정 요청을 반영했다고 보고 차단 오류를 지운다 (다시 검토하면 남은 지적만 나온다)
      run.findings = run.findings.filter((f) => f.severity !== 'critical').map((f) => ({ ...f, iteration: (f.iteration as number) + 1 }))
      moveTo(run, { status: 'designing', stage: 'designing', nextRevision: true }, [...toReview])
      return statusOf(run)
    }
    if (run.findings.some((f) => f.severity === 'critical')) {
      // 백엔드 api/errors.py BlockingFindingsError와 같은 응답 (ADR-0010)
      throw new Reject(422, 'INVALID_RESPONSE', '차단 오류가 남아 있어 승인할 수 없습니다.', run.run_id)
    }
    moveTo(run, { status: 'exporting', stage: 'exporting' }, [{ status: 'completed', stage: 'exporting' }])
    return statusOf(run)
  }

  function cancel(run: MockRun, expectedRevision: unknown): RunStatus {
    if (typeof expectedRevision !== 'number') {
      throw new Reject(422, 'INVALID_REQUEST', 'expected_revision이 필요합니다.', run.run_id)
    }
    if (FINISHED.includes(run.status)) throw new Reject(409, 'RUN_REVISION_CONFLICT', STATE_MESSAGE, run.run_id)
    if (expectedRevision !== run.revision) {
      throw new Reject(409, 'RUN_REVISION_CONFLICT', REVISION_MESSAGE, run.run_id)
    }
    if (run.status === 'cancel_requested') return statusOf(run)
    if (WAITING.includes(run.status)) {
      // 대기·사람 확인 중이면 바로 취소 (ADR-0012)
      moveTo(run, { status: 'cancelled', stage: run.stage }, [])
    } else {
      // 실행 중이면 지금 하던 호출이 끝난 뒤 취소된다
      moveTo(run, { status: 'cancel_requested', stage: run.stage }, [
        { status: 'cancelled', stage: run.stage, ms: cancelMs },
      ])
    }
    return statusOf(run)
  }

  function artifact(run: MockRun, kind: string, url: URL): Response {
    const fileFormat = url.searchParams.get('file_format') ?? ''
    const revision = Number(url.searchParams.get('revision'))
    const formats: readonly string[] | undefined = ARTIFACT_FORMATS[kind as keyof typeof ARTIFACT_FORMATS]
    if (!formats || !formats.includes(fileFormat) || !Number.isInteger(revision)) {
      throw new Reject(422, 'ARTIFACT_FORMAT_UNSUPPORTED', '이 산출물은 그 형식으로 받을 수 없습니다.', run.run_id)
    }
    const approved = run.approvedRevisions.has(revision)
    if (kind === 'review' || !run.artifactRevisions.has(revision) || ((fileFormat === 'pdf' || kind === 'manifest') && !approved)) {
      throw new Reject(
        409,
        'ARTIFACT_NOT_READY',
        '요청한 산출물이 아직 없습니다. PDF는 승인한 revision에서만 받을 수 있습니다.',
        run.run_id,
      )
    }
    const fileName = `specton-${kind}-r${revision}${approved ? '' : '-draft'}.${fileFormat}`
    const text =
      kind === 'erd' && fileFormat === 'mmd'
        ? run.erdAttack
          ? ERD_ATTACK_SAMPLE
          : ERD_SAMPLE
        : kind === 'ddl'
          ? DDL_SAMPLE
           : kind === 'rtm' && fileFormat === 'csv'
            ? mockRtmCsv(run.requirements as AnalysedRequirement[], (run.large ? LARGE_DESIGN_ITEMS : designItems) as DesignItem[], run.extraction as ExtractionBlock[])
            : kind === 'manifest'
              ? JSON.stringify({ mock: true, run_id: run.run_id, revision, approved })
              : `mock ${kind} r${revision} (${fileFormat})\n`
    return new HttpResponse(text, {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Disposition': `attachment; filename="${fileName}"`,
      },
    })
  }

  // ── SSE (백엔드 api/runs.py stream_events와 같은 규칙) ────────

  /** Last-Event-ID 검사. 숫자가 아니거나 아직 없는 ID면 409 (docs/06 「SSE」) */
  function replayFrom(run: MockRun, header: string | null): number {
    if (header === null || header === '') return 0
    if (!/^\d+$/.test(header) || Number(header) > run.events.length) {
      throw new Reject(
        409,
        'EVENT_REPLAY_EXPIRED',
        '이어 받을 수 없는 이벤트 위치입니다. 상태를 조회한 뒤 다시 연결하세요.',
        run.run_id,
      )
    }
    return Number(header)
  }

  /** 지난 이벤트를 다시 보내고 새 이벤트를 이어 보낸다. 끝난 실행은 다 보낸 뒤 닫는다. */
  function eventStream(run: MockRun, after: number, signal: AbortSignal): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    let timer: ReturnType<typeof setInterval> | undefined
    let last = after
    const stop = () => clearInterval(timer)
    return new ReadableStream({
      start(controller) {
        const tick = () => {
          advance(run)
          for (const e of run.events.slice(last)) {
            controller.enqueue(encoder.encode(`id: ${e.id}\nevent: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`))
            last = e.id
          }
          if (FINISHED.includes(run.status) && last === run.events.length) {
            stop()
            controller.close()
          }
        }
        signal.addEventListener('abort', stop)
        timer = setInterval(tick, pollMs)
        tick()
      },
      cancel: stop,
    })
  }

  // ── MSW 연결 ──────────────────────────────────────────
  // 주소 앞의 *는 어느 서버 주소든 맞춘다는 뜻 (브라우저·테스트 모두에서 쓰기 위해)

  async function respond(handle: () => Response | object | Promise<Response | object>, status = 200) {
    await delay() // 브라우저에서는 실제처럼 약간 늦게, 테스트에서는 바로
    try {
      const result = await handle()
      return result instanceof Response ? result : HttpResponse.json(result, { status })
    } catch (err) {
      if (err instanceof Reject) return HttpResponse.json(err.body, { status: err.status })
      throw err
    }
  }

  const handlers = [
    http.get('*/health', () => respond(() => ({ status: 'ok', version: 'mock' }))),

    http.post('*/runs', ({ request }) =>
      respond(async () => {
        const form = await request.formData()
        const file = form.get('file')
        const pack = form.get('pack')
        return createRun(file instanceof File ? file : null, typeof pack === 'string' ? pack : null)
      }, 202),
    ),

    http.get('*/runs', ({ request }) => respond(() => listRuns(new URL(request.url)))),

    http.get('*/runs/:id', ({ params }) => respond(() => statusOf(findRun(String(params.id))))),

    http.get('*/runs/:id/events', ({ params, request }) =>
      respond(() => {
        const run = findRun(String(params.id))
        const after = replayFrom(run, request.headers.get('Last-Event-ID'))
        return new HttpResponse(eventStream(run, after, request.signal), {
          headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        })
      }),
    ),

    http.get('*/runs/:id/view', ({ params, request }) =>
      respond(() => view(findRun(String(params.id)), new URL(request.url))),
    ),

    http.post('*/runs/:id/resume', ({ params, request }) =>
      respond(async () => {
        const run = findRun(String(params.id))
        return resume(run, (await request.json()) as ResumeRequest)
      }, 202),
    ),

    http.post('*/runs/:id/cancel', ({ params, request }) =>
      respond(async () => {
        const run = findRun(String(params.id))
        const body = (await request.json().catch(() => ({}))) as { expected_revision?: unknown }
        return cancel(run, body.expected_revision)
      }, 202),
    ),

    http.get('*/runs/:id/artifacts/:kind', ({ params, request }) =>
      respond(() => artifact(findRun(String(params.id)), String(params.kind), new URL(request.url))),
    ),
  ]

  return {
    handlers,
    /** 저장한 실행을 모두 지운다 (테스트용) */
    reset: () => runs.clear(),
    /** SSE 이벤트 기록 (테스트에서 /events 스트림과 비교한다) */
    eventsOf: (runId: string) => {
      const run = runs.get(runId)
      if (run) advance(run)
      return run?.events ?? []
    },
  }
}

/** 제외한 원문의 ID가 남은 원문의 「관련 요구사항」에 나오면 경고 payload (백엔드 graph.py와 같은 기준) */
function relatedWarningsOf(blocks: Item[]): Item[] {
  const excluded = blocks.filter((b) => b.user_decision === 'excluded' && typeof b.source_id === 'string')
  const remaining = blocks.filter((b) => b.user_decision !== 'excluded' && typeof b.source_related_requirements === 'string')
  return excluded.flatMap((block) => {
    const id = (block.source_id as string).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const sameId = new RegExp(`(?<![\\p{L}\\p{N}_-])${id}(?![\\p{L}\\p{N}_-])`, 'u')
    const related = remaining.filter((r) => sameId.test(r.source_related_requirements as string)).map((r) => r.block_id)
    return related.length
      ? [{ warning: 'excluded_related', block_id: block.block_id, source_id: block.source_id, related_block_ids: related }]
      : []
  })
}

// ── 답변 검사 (백엔드와 같은 422 조건) ────────────────────

function checkExtraction(run: MockRun, answer: ExtractionResponse, invalid: (m: string) => Reject) {
  const excluded = answer.excluded_blocks ?? []
  if (!answer.confirmed && excluded.length > 0) throw invalid('중단할 때는 제외 목록을 비워 주세요.')
  if (!answer.confirmed) return
  const byId = new Map(run.extraction.map((b) => [b.block_id as string, b]))
  const seen = new Set<string>()
  for (const { block_id, reason } of excluded) {
    const block = byId.get(block_id)
    if (!block) throw invalid(`${block_id}: 없는 블록입니다.`)
    if (seen.has(block_id)) throw invalid(`${block_id}: 같은 블록을 두 번 제외했습니다.`)
    seen.add(block_id)
    if (block.extraction_status === 'pass') throw invalid(`${block_id}: 문제없는 블록은 제외할 수 없습니다.`)
    if (block.extraction_status === 'review' && !reason?.trim()) {
      throw invalid(`${block_id}: 확인 필요 블록을 제외할 때는 사유를 적어 주세요.`)
    }
  }
  for (const block of run.extraction) {
    if (block.extraction_status === 'fail' && !seen.has(block.block_id as string)) {
      throw invalid(`${block.block_id}: 읽지 못한 블록은 제외해야 합니다.`)
    }
  }
}

function applyRequirements(run: MockRun, answer: RequirementsResponse, invalid: (m: string) => Reject) {
  const ids = new Set(run.requirements.map((r) => r.id as string))
  const seen = new Set<string>()
  for (const { req_id, action, texts } of answer.answers) {
    if (!ids.has(req_id)) throw invalid(`${req_id}: 없는 요구사항입니다.`)
    if (seen.has(req_id)) throw invalid(`${req_id}: 같은 요구사항에 답을 두 번 보냈습니다.`)
    seen.add(req_id)
    const counts = { keep: texts.length === 0, edit: texts.length === 1, split: texts.length >= 2 }
    if (!counts[action]) throw invalid(`${req_id}: ${action}의 문장 수가 맞지 않습니다.`)
    if (texts.some((t) => !t.trim())) throw invalid(`${req_id}: 빈 문장이 있습니다.`)
  }
  // 답을 반영한다: edit은 문장 교체, split은 첫 조각이 원래 ID, 나머지는 새 ID
  let nextNumber = run.requirements.length + 1
  const result: Item[] = []
  for (const req of run.requirements) {
    const answerFor = answer.answers.find((a) => a.req_id === req.id)
    if (!answerFor || answerFor.action === 'keep') {
      result.push(req)
    } else if (answerFor.action === 'edit') {
      result.push({ ...req, text: answerFor.texts[0].trim(), quality_issues: [] })
    } else {
      answerFor.texts.forEach((text, i) => {
        const id = i === 0 ? req.id : `REQ-${String(nextNumber++).padStart(2, '0')}`
        result.push({ ...req, id, parent_id: i === 0 ? null : req.id, text: text.trim(), quality_issues: [] })
      })
    }
  }
  run.requirements = result
}
