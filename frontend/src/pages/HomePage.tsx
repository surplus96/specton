import type { CSSProperties } from 'react'
import { Button, Flex } from 'antd'
import { useNavigate } from 'react-router'
import { colors, type, weights } from '../theme.ts'
import { FORMATS_LABEL } from './upload/rules.ts'

// 첫 화면: 팀·프로젝트 소개 (/). "시작하기"를 누르면 UI-01(업로드, /start)로 간다.
// 대형 강의장 프로젝터 기준(theme.ts): 남색 면 + 흰 글자, 흰 카드 + 진한 테두리, 큰 글자.
const TEAM_NAME = '설계로'
const PROJECT_NAME = 'Specton'
const PARTNERS = ['한화내일아카데미', '한화시스템', '고용노동부']

// 프로젝트 한 단락 소개 (CLAUDE.md 규칙: LLM은 판단만, ID·SQL·도면은 코드가 만든다)
const PROJECT_INTRO =
  'Specton은 고객의 요구사항 정의서를 읽어 기능 명세 · ERD · DDL · RTM을 만드는 AI 설계 도우미입니다. ' +
  'AI는 판단만 하고 ID · SQL · 도면은 코드가 만들며, 사람이 확인하고 승인한 결과만 내보냅니다.'

// 팀원 (역할: docs/08-roles.md). 작업 흐름 순서: 입력·분석 → 기능 → 데이터 모델 → 관계·시각화
const LEADER = { name: '최태영', role: '팀장 · 실행 제어 · 통합' }
const MEMBERS = [
  { name: '김희영', role: '입력 · 분석 · 평가' },
  { name: '박성진', role: '기능 · API · 저장' },
  { name: '김유경', role: '데이터 모델 · 검증' },
  { name: '김순재', role: '관계 · 시각화 · 웹' },
]

// 무엇을 하는 도구인지 세 단계로 (docs/09-ui-flow.md: 업로드 → 확인·승인 → 결과 보기)
// 카드 바탕은 파랑 → 진한 파랑 → 남색. 모두 흰 글자와 6.7:1 이상
const FLOW = [
  { title: '올리기', text: `요구사항 정의서(${FORMATS_LABEL})를 올립니다.`, bg: colors.primary },
  { title: '확인하기', text: '추출·분석 결과를 사람이 확인하고 승인합니다.', bg: colors.primaryStrong },
  { title: '받기', text: '기능 명세 · ERD · DDL · RTM을 내려받습니다.', bg: colors.navy },
]

const card: CSSProperties = {
  background: colors.canvas,
  border: `1.5px solid ${colors.border}`,
  borderRadius: 16,
}

const label: CSSProperties = {
  fontSize: 15,
  fontWeight: weights.strong,
  letterSpacing: '0.08em',
  color: colors.primary,
  marginBottom: 8,
}

const heading: CSSProperties = {
  ...type.section,
  margin: '0 0 16px',
  color: colors.ink,
}

function HomePage() {
  const navigate = useNavigate()

  return (
    <Flex vertical gap={28} style={{ maxWidth: 1120, margin: '0 auto' }}>
      {/* 소개: 남색 면 + 흰 글자 */}
      <section
        style={{
          textAlign: 'center',
          padding: 'clamp(48px, 8vw, 88px) 16px',
          background: colors.navy,
          borderRadius: 16,
        }}
      >
        <span
          style={{
            display: 'inline-block',
            background: colors.primary,
            color: colors.onDark,
            fontSize: 18,
            fontWeight: weights.strong,
            padding: '6px 20px',
            borderRadius: 980,
          }}
        >
          팀 {TEAM_NAME}
        </span>
        <h1
          style={{
            ...type.hero,
            margin: '24px 0 0',
            color: colors.onDark,
          }}
        >
          Spec<span style={{ color: colors.onDarkMuted }}>ton</span>
        </h1>
        <div style={{ width: 72, height: 5, background: colors.primary, borderRadius: 3, margin: '24px auto' }} />
        <p style={{ fontSize: 'clamp(22px, 3.2vw, 30px)', fontWeight: weights.strong, color: colors.onDark, margin: 0 }}>
          요구사항 정의서에서 설계 산출물까지
        </p>
        <p style={{ fontSize: 20, color: colors.onDarkMuted, margin: '12px 0 36px', wordBreak: 'keep-all' }}>
          문서를 올리면 기능 명세와 데이터베이스 설계를 만들고, 사람이 확인한 결과만 내보냅니다.
        </p>
        <Button type="primary" size="large" onClick={() => navigate('/start')}>
          시작하기
        </Button>
      </section>

      {/* 프로젝트 소개 */}
      <section aria-label="프로젝트 소개" style={{ ...card, padding: 'clamp(24px, 4vw, 40px)' }}>
        <div style={label}>PROJECT</div>
        <h2 style={heading}>{PROJECT_NAME}이란?</h2>
        <p style={{ fontSize: 20, lineHeight: 1.7, color: colors.ink, margin: 0, wordBreak: 'keep-all' }}>
          {PROJECT_INTRO}
        </p>
      </section>

      {/* 흐름 세 단계: 파랑 → 진한 파랑 → 남색, 흰 글자 */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 16,
        }}
      >
        {FLOW.map((step, i) => (
          <div key={step.title} style={{ background: step.bg, borderRadius: 16, padding: 32 }}>
            <div style={{ fontSize: 56, fontWeight: weights.display, lineHeight: 1, color: colors.onDarkMuted }}>{i + 1}</div>
            <div style={{ ...type.card, margin: '14px 0 10px', color: colors.onDark }}>
              {step.title}
            </div>
            <div style={{ fontSize: 19, lineHeight: 1.6, color: colors.onDark, wordBreak: 'keep-all' }}>{step.text}</div>
          </div>
        ))}
      </section>

      {/* 팀 소개: 팀장은 파랑 카드, 팀원은 흰 카드 + 진한 테두리 */}
      <section aria-label="팀 소개">
        <div style={label}>TEAM</div>
        <h2 style={heading}>팀 {TEAM_NAME}</h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
            gap: 14,
          }}
        >
          {[LEADER, ...MEMBERS].map((person) => {
            const leader = person === LEADER
            return (
              <div
                key={person.name}
                style={{
                  ...card,
                  background: leader ? colors.primary : colors.canvas,
                  border: `1.5px solid ${leader ? colors.primary : colors.border}`,
                  padding: '26px 22px',
                }}
              >
                <div style={{ ...type.card, color: leader ? colors.onDark : colors.ink }}>
                  {person.name}
                </div>
                <div
                  style={{
                    fontSize: 17,
                    fontWeight: weights.strong,
                    marginTop: 8,
                    color: leader ? colors.onDark : colors.inkMuted,
                    wordBreak: 'keep-all',
                  }}
                >
                  {person.role}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 함께한 곳: 남색 띠 */}
      <footer
        style={{
          textAlign: 'center',
          background: colors.navy,
          borderRadius: 16,
          borderTop: `5px solid ${colors.primary}`,
          padding: '36px 16px',
        }}
      >
        <Flex justify="center" align="center" wrap gap="10px 24px">
          {PARTNERS.map((name, i) => (
            <Flex key={name} align="center" gap={24}>
              {i > 0 && <span style={{ color: colors.onDarkMuted }}>●</span>}
              <span style={{ fontSize: 20, fontWeight: weights.strong, color: colors.onDark }}>{name}</span>
            </Flex>
          ))}
        </Flex>
        <p style={{ fontSize: 16, color: colors.onDarkMuted, margin: '18px 0 0' }}>
          © 2026 팀 {TEAM_NAME} · {PROJECT_NAME}
        </p>
      </footer>
    </Flex>
  )
}

export default HomePage
