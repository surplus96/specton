import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Alert, Button, Flex, Form, Select, Typography, Upload } from 'antd'
import type { UploadFile } from 'antd'
import { createRun } from '../api/client.ts'
import type { Pack } from '../api/types.ts'
import StageSteps from '../layout/StageSteps.tsx'
import PageCard from '../layout/PageCard.tsx'
import {
  ACCEPT_ATTR,
  ACCEPTED_FORMATS,
  MAX_UPLOAD_MB,
  PACK_LABELS,
  PACK_OPTIONS,
  checkFile,
  placeError,
} from './upload/rules.ts'

// UI-01 실행 시작 (docs/09-ui-flow.md): 파일 업로드, 팩 선택, 지원 형식·한도 안내.
// - 파일·팩 오류는 해당 칸 아래에 보인다. 그 밖의 오류는 버튼 위 안내로 보인다.
// - 실행 요청 중에는 버튼을 잠근다(중복 클릭 방지). 202를 받으면 /run/{id}로 간다.
// 배치는 기본 부품을 세로로 쌓은 임시 모양이다. 디자인은 나중에 이 파일만 고친다.
function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [pack, setPack] = useState<Pack | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [packError, setPackError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // 상태 갱신은 다음 렌더링에 반영되므로, 빠른 두 번 클릭은 ref로 막는다.
  const inFlight = useRef(false)

  const fileList: UploadFile[] = file
    ? [{ uid: 'selected', name: file.name, status: fileError ? 'error' : 'done' }]
    : []

  function chooseFile(chosen: File) {
    setFile(chosen)
    setFileError(checkFile(chosen))
    setFormError(null)
  }

  function choosePack(value: Pack) {
    setPack(value)
    setPackError(null)
    setFormError(null)
  }

  async function submit() {
    if (inFlight.current) return
    const missingFile = file ? null : '요구사항 문서를 골라 주세요.'
    const missingPack = pack ? null : '도메인 팩을 골라 주세요.'
    if (missingFile) setFileError(missingFile)
    if (missingPack) setPackError(missingPack)
    if (!file || !pack || fileError) return

    inFlight.current = true
    setSubmitting(true)
    setFormError(null)
    try {
      const run = await createRun(file, pack)
      navigate(`/run/${encodeURIComponent(run.run_id)}`)
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

  const formats = ACCEPTED_FORMATS.map((f) => `.${f}`).join(' · ')

  return (
    <Flex vertical gap={24}>
      <StageSteps current="UI-01" />
      <PageCard
        title="요구사항 문서 올리기"
        subtitle="요구사항 정의서(.xlsx · .csv · .hwpx)를 올리면 기능 명세·ERD·DDL·RTM을 만듭니다."
      >
        <Form layout="vertical" onFinish={submit} disabled={submitting}>
          <Form.Item
            label="요구사항 문서"
            required
            validateStatus={fileError ? 'error' : undefined}
            help={fileError ?? `${formats} · 최대 ${MAX_UPLOAD_MB}MB · 파일 1개`}
          >
            <Upload.Dragger
              accept={ACCEPT_ATTR}
              maxCount={1}
              fileList={fileList}
              beforeUpload={(chosen) => {
                chooseFile(chosen)
                return false // 고르기만 하고 올리기는 '설계 시작'에서 한다
              }}
              onRemove={() => {
                setFile(null)
                setFileError(null)
              }}
            >
              <Typography.Paragraph>파일을 끌어다 놓거나 눌러서 고르세요</Typography.Paragraph>
              <Typography.Text type="secondary">
                HWP는 한글에서 HWPX로 저장해 올려 주세요. PDF는 지원하지 않습니다.
              </Typography.Text>
            </Upload.Dragger>
          </Form.Item>

          <Form.Item
            label="도메인 팩"
            required
            validateStatus={packError ? 'error' : undefined}
            help={packError ?? (pack ? PACK_LABELS[pack].description : '문서의 업무 분야를 고르세요')}
          >
            <Select<Pack>
              placeholder="팩 선택"
              options={PACK_OPTIONS}
              value={pack ?? undefined}
              onChange={choosePack}
            />
          </Form.Item>

          {formError && (
            <Form.Item>
              <Alert type="error" showIcon title={formError} />
            </Form.Item>
          )}

          <Form.Item>
            <Button type="primary" htmlType="submit" size="large" loading={submitting}>
              {submitting ? '접수 중…' : '설계 시작'}
            </Button>
          </Form.Item>
        </Form>
      </PageCard>
    </Flex>
  )
}

export default UploadPage
