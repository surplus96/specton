import Icon, { type IconName } from '../../layout/Icon.tsx'
import StatusTag from '../../layout/StatusTag.tsx'
import type { ArtifactRef, DesignItem } from '../../api/viewItems.ts'
import { colors, weights } from '../../theme.ts'
import { pipelineStages, type PipelineStage, type WorkspaceTab } from './pipeline.ts'

// 산출물 파이프라인: 요구사항 → 기능 명세 → ERD → DDL → RTM (Figma 시안의 「산출물 파이프라인」).
// 카드마다 숫자와 상태(미완성·초안·승인본)를 글자로 보이고, DDL은 검증 상태도 보인다.
// 누르면 결과 작업공간의 해당 탭으로 간다. 색은 theme.ts 그대로(흰 카드 + 테두리, 상태는 StatusTag).
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
    <section aria-label="산출물 파이프라인">
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 6, flexWrap: 'wrap' }}>
        {stages.map((s, i) => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 6, flex: '1 1 170px', minWidth: 170 }}>
            <button
              type="button"
              onClick={() => onOpen(s.tab)}
              aria-label={`${s.title}: ${s.status.text}${s.extra ? `, ${s.extra.text}` : ''}. 결과 작업공간에서 보기`}
              style={{
                flex: 1,
                textAlign: 'left',
                cursor: 'pointer',
                background: colors.canvas,
                border: `1.5px solid ${colors.border}`,
                borderRadius: 16,
                padding: '14px 16px',
                color: colors.ink,
                font: 'inherit',
                height: '100%',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ color: colors.primary, display: 'inline-flex' }}>
                  <Icon name={ICON[s.key]} size={24} />
                </span>
                <StatusTag tone={s.status.tone}>{s.status.text}</StatusTag>
              </div>
              <div style={{ marginTop: 10, fontSize: 13, fontWeight: weights.strong, color: colors.inkMuted, letterSpacing: '0.04em' }}>
                {s.code}
              </div>
              <div style={{ fontSize: 20, fontWeight: weights.display, lineHeight: 1.25 }}>{s.title}</div>
              <div style={{ marginTop: 4, fontSize: 15, color: colors.inkMuted }}>{s.detail}</div>
              {s.extra && (
                <div style={{ marginTop: 8 }}>
                  <StatusTag tone={s.extra.tone}>{s.extra.text}</StatusTag>
                </div>
              )}
            </button>
            {i < stages.length - 1 && (
              <span aria-hidden="true" style={{ color: colors.border, display: 'inline-flex' }}>
                <Icon name="chevron" size={18} />
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

export default Pipeline
