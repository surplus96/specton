import type { CSSProperties } from 'react'
import { Flex } from 'antd'
import { useNavigate } from 'react-router'
import { colors, type, weights } from '../theme.ts'
import { FORMATS_LABEL } from './upload/rules.ts'

// 첫 화면: 팀·프로젝트 소개 (/). 가운데 버튼을 누르면 UI-01(업로드, /start)로 간다.
// 흰 바탕 + 가운데 정렬의 단순한 모양. 남색 글자에 「ton」만 파랑으로 강조한다.
const TEAM_NAME = '설계로'
const PROJECT_NAME = 'Specton'
const PARTNERS = ['한화내일아카데미', '한화시스템', '고용노동부']

// 팀원 (역할: docs/08-roles.md). 작업 흐름 순서: 입력·분석 → 기능 → 데이터 모델 → 관계·시각화
const TEAM = [
  { name: '최태영', role: '실행 제어 · 통합', leader: true },
  { name: '김희영', role: '입력 · 분석 · 평가' },
  { name: '박성진', role: '기능 · API · 저장' },
  { name: '김유경', role: '데이터 모델 · 검증' },
  { name: '김순재', role: '관계 · 시각화 · 웹' },
]

// 무엇을 하는 도구인지 세 단계로 (docs/09-ui-flow.md: 업로드 → 확인·승인 → 결과 보기)
const STEPS = ['올리기', '확인하기', '받기']

const pill: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 16px',
  border: `1.5px solid ${colors.line}`,
  borderRadius: 999,
  background: colors.canvas,
  fontSize: 17,
  color: colors.ink,
}

function UploadIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={colors.primary} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 15V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
    </svg>
  )
}

function HomePage() {
  const navigate = useNavigate()

  return (
    <Flex vertical style={{ maxWidth: 1120, margin: '0 auto', minHeight: 'calc(100vh - 160px)' }}>
      {/* 소개: 가운데 정렬 */}
      <section
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          padding: 'clamp(48px, 10vh, 120px) 0 48px',
        }}
      >
        <div style={{ fontSize: 18, fontWeight: weights.strong, color: colors.inkMuted }}>팀 {TEAM_NAME}</div>
        <h1 style={{ ...type.hero, margin: '20px 0 0', color: colors.navy }}>
          Spec<span style={{ color: colors.primary }}>ton</span>
        </h1>
        <p style={{ fontSize: 'clamp(19px, 2.2vw, 24px)', color: colors.inkMuted, margin: '28px 0 40px' }}>
          요구사항 정의서({FORMATS_LABEL})를 올리면 설계 산출물을 만들어 드려요
        </p>

        {/* 시작 버튼: 알약 모양 긴 버튼 */}
        <button type="button" className="home-start" onClick={() => navigate('/start')}>
          <UploadIcon />
          <span style={{ flex: 1, textAlign: 'left' }}>사람이 확인한 결과만 내보내요</span>
          <span aria-hidden="true" style={{ fontSize: 24 }}>
            →
          </span>
        </button>

        {/* 세 단계 */}
        <Flex justify="center" align="center" wrap gap="12px 16px" style={{ marginTop: 32 }}>
          {STEPS.map((step, i) => (
            <Flex key={step} align="center" gap={16}>
              {i > 0 && (
                <span aria-hidden="true" style={{ color: colors.line, fontSize: 20 }}>
                  →
                </span>
              )}
              <span style={pill}>
                <strong style={{ color: colors.primary, fontWeight: weights.display }}>{i + 1}</strong>
                {step}
              </span>
            </Flex>
          ))}
        </Flex>

        {/* 팀원 */}
        <section aria-label="팀 소개" style={{ marginTop: 'clamp(48px, 8vh, 88px)', width: '100%' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
              gap: 12,
            }}
          >
            {TEAM.map((person) => (
              <div
                key={person.name}
                style={{
                  padding: '18px 16px',
                  border: `1.5px solid ${person.leader ? colors.primary : colors.line}`,
                  borderRadius: 16,
                  background: colors.canvas,
                }}
              >
                <div style={{ fontSize: 20, fontWeight: weights.display, color: colors.ink }}>
                  {person.name}
                  {person.leader && (
                    <span style={{ marginLeft: 8, fontSize: 14, fontWeight: weights.strong, color: colors.primary }}>팀장</span>
                  )}
                </div>
                <div style={{ fontSize: 15, marginTop: 6, color: colors.inkMuted }}>
                  {person.role}
                </div>
              </div>
            ))}
          </div>
        </section>
      </section>

      {/* 함께한 곳 */}
      <footer
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '8px 24px',
          padding: '18px 24px',
          background: '#f1f5f9',
          borderTop: `1px solid ${colors.line}`,
          fontSize: 15,
          color: colors.inkMuted,
        }}
      >
        <span>{PARTNERS.join(' · ')}</span>
        <span>
          © 2026 팀 {TEAM_NAME} · {PROJECT_NAME}
        </span>
      </footer>
    </Flex>
  )
}

export default HomePage
