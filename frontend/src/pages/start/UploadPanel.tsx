import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router'
import { createRun } from '../../api/client.ts'
import { notifyRunsChanged, rememberRunName } from '../../api/runNames.ts'
import type { Pack } from '../../api/types.ts'
import Icon from '../../layout/Icon.tsx'
import Button from '../../ui/Button.tsx'
import Notice from '../../ui/Notice.tsx'
import {
  ACCEPT_ATTR,
  ENABLED_PACKS,
  MAX_UPLOAD_MB,
  PACK_OPTIONS,
  checkFile,
  placeError,
} from '../upload/rules.ts'

// 새 작업 (UI-01 실행 시작): 파일 끌어다 놓기·선택, 업무 분야(팩), 진행 방식, 설계 시작.
// - 고른 파일과 서버에 올라간 것을 구분한다. 파일을 골랐다고 올린 것처럼 보이지 않는다(디자인 시스템 8).
// - 파일·팩 오류는 그 칸 아래, 나머지 오류는 버튼 위에 보인다 (upload/rules.ts placeError).
// - 요청 중에는 버튼을 잠근다(빠른 두 번 클릭은 ref로 막는다). 202를 받으면 주소를 /?run=<id>로 바꾼다.
// - 실행은 기존 확인 흐름을 사용한다. 지원하지 않는 진행 방식은 화면에 노출하지 않는다.
const FORMAT_TEXT = 'Excel · CSV · HWP · HWPX'

function sizeText(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function UploadPanel() {
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [pack, setPack] = useState<Pack | null>(ENABLED_PACKS.length === 1 ? ENABLED_PACKS[0] : null)
  const [over, setOver] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)
  const [packError, setPackError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const inFlight = useRef(false)

  function choose(chosen: File | undefined) {
    if (!chosen) return
    setFile(chosen)
    setFileError(checkFile(chosen))
    setFormError(null)
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (submitting) return
    const files = e.dataTransfer.files
    if (files.length > 1) {
      setFormError('파일은 한 번에 1개만 올릴 수 있어요.')
      return
    }
    choose(files[0])
  }

  function clear() {
    setFile(null)
    setFileError(null)
    setFormError(null)
    if (input.current) input.current.value = ''
  }

  async function submit() {
    if (inFlight.current) return
    if (!file) setFileError('요구사항 문서를 골라 주세요.')
    if (!pack) setPackError('업무 분야를 골라 주세요.')
    if (!file || !pack || fileError) return
    inFlight.current = true
    setSubmitting(true)
    setFormError(null)
    try {
      const run = await createRun(file, pack)
      rememberRunName(run.run_id, file.name)
      notifyRunsChanged()
      navigate(`/?run=${encodeURIComponent(run.run_id)}`)
    } catch (err) {
      const { place, message } = placeError(err)
      if (place === 'file') setFileError(message)
      else if (place === 'pack') setPackError(message)
      else setFormError(message)
    } finally {
      inFlight.current = false
      setSubmitting(false)
    }
  }

  return (
    <div className="stack">
      <div
        className={`drop${over ? ' drop--over' : ''}${fileError ? ' drop--error' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          if (!submitting) setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          type="file"
          accept={ACCEPT_ATTR}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => {
            choose(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        {!file ? (
          <>
            <span className="drop__icon" aria-hidden="true">
              <Icon name="fileUp" size={24} />
            </span>
            <div className="drop__title">요구사항 정의서를 여기에 끌어다 놓으세요</div>
            <div className="drop__formats">
              {FORMAT_TEXT} · 최대 {MAX_UPLOAD_MB}MB · 파일 1개
            </div>
            <Button size="lg" onClick={() => input.current?.click()} style={{ marginTop: 10 }}>
              파일 선택
            </Button>
          </>
        ) : (
          <>
            <div className="file-chip">
              <span className="file-chip__icon" aria-hidden="true">
                <Icon name="file" size={16} />
              </span>
              <div style={{ minWidth: 0 }}>
                <div className="file-chip__name">{file.name}</div>
                <div className="file-chip__meta">
                  {sizeText(file.size)} · {fileError ? '올릴 수 없는 파일' : "파일을 골랐어요. '설계 시작'을 누르면 올라가요."}
                </div>
              </div>
              <button type="button" className="icon-btn" onClick={clear} aria-label="고른 파일 빼기" disabled={submitting}>
                <Icon name="x" size={18} />
              </button>
            </div>
            {fileError && (
              <div className="field__error" role="alert">
                {fileError}
              </div>
            )}
            <div className="row" style={{ justifyContent: 'center', marginTop: 6 }}>
              <Button variant="secondary" onClick={() => input.current?.click()} disabled={submitting}>
                다른 파일
              </Button>
              <Button
                size="lg"
                onClick={submit}
                loading={submitting}
                loadingText="파일을 보내고 있어요"
                disabled={!!fileError}
                iconEnd={<Icon name="arrowRight" size={18} />}
              >
                설계 시작
              </Button>
            </div>
          </>
        )}

      </div>

      <div className="pack-row">
        <label htmlFor="pack">업무 분야</label>
        <select
          id="pack"
          className="select"
          value={pack ?? ''}
          aria-invalid={!!packError}
          aria-describedby={packError ? 'pack-help' : undefined}
          disabled={submitting}
          onChange={(e) => {
            setPack((e.target.value || null) as Pack | null)
            setPackError(null)
            setFormError(null)
          }}
        >
          {ENABLED_PACKS.length > 1 && <option value="">업무 분야 선택</option>}
          {PACK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {packError && <span id="pack-help" className="field__error" role="alert">{packError}</span>}
      </div>

      {formError && <Notice kind="error" title={formError} />}

    </div>
  )
}

export default UploadPanel
