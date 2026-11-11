import type { ArtifactRef, DesignItem } from '../../api/viewItems.ts'
import Icon, { type IconName } from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import { pipelineStages, type PipelineStage, type WorkspaceTab } from './pipeline.ts'

// 산출물 파이프라인: 요구사항 → 기능 명세 → ERD → DDL → RTM.
// 카드마다 숫자와 상태(미완성·초안·승인본)를 글자로 보이고, DDL은 검증 상태도 보인다. 누르면 결과 작업공간의 해당 탭.
type Props = {
  design: readonly DesignItem[]
  artifacts: readonly ArtifactRef[]
  onOpen: (tab: WorkspaceTab) => void
}

const ICON: Record<PipelineStage['key'], IconName> = {
  requirements: 'file',
  functions: 'list',
  erd: 'database',
  ddl: 'code',
  rtm: 'link',
}

function Pipeline({ design, artifacts, onOpen }: Props) {
  const stages = pipelineStages(design, artifacts)
  return (
    <div className="pipeline">
      {stages.map((s, i) => (
        <div key={s.key} className="pipeline__item">
          <button
            type="button"
            className="card card--link pipeline__card"
            style={{ padding: 18 }}
            onClick={() => onOpen(s.tab)}
            aria-label={`${s.title}: ${s.status.text}${s.extra ? `, ${s.extra.text}` : ''}. 결과 작업공간에서 보기`}
          >
            <span className="row row--between">
              <Icon name={ICON[s.key]} size={22} />
              <StatusTag tone={s.status.tone}>{s.status.text}</StatusTag>
            </span>
            <span className="pipeline__code">{s.code}</span>
            <span className="pipeline__title">{s.title}</span>
            <span className="muted" style={{ fontSize: 14 }}>
              {s.detail}
            </span>
            {s.extra && (
              <span style={{ marginTop: 6 }}>
                <StatusTag tone={s.extra.tone}>{s.extra.text}</StatusTag>
              </span>
            )}
          </button>
          {i < stages.length - 1 && (
            <span aria-hidden="true" className="subtle">
              <Icon name="chevron" size={18} />
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

export default Pipeline
