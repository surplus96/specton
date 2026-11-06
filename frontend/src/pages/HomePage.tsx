import { Button, Flex } from 'antd'
import { useNavigate } from 'react-router'
import { colors } from '../theme.ts'

// 팀·프로젝트 소개 (/intro). "시작하기"를 누르면 UI-01(업로드)로 간다.
const TEAM_NAME = '설계로'
const PROJECT_NAME = 'Specton'
const PARTNERS = ['한화내일아카데미', '한화시스템', '고용노동부']

// 무엇을 하는 도구인지 세 줄로 (docs/09-ui-flow.md의 화면 묶음: 업로드 → 확인·승인 → 결과 보기)
// 카드 바탕은 한화 오렌지 100% → 70% → 50%
const FLOW = [
  { title: '올리기', text: '요구사항 정의서(.xlsx · .csv)를 올립니다.', bg: colors.orange },
  { title: '확인하기', text: '추출·분석 결과를 사람이 확인하고 승인합니다.', bg: colors.orange70 },
  { title: '받기', text: '기능 명세 · ERD · DDL · RTM을 내려받습니다.', bg: colors.orange50 },
]

function HomePage() {
  const navigate = useNavigate()

  return (
    <Flex vertical gap={24}>
      {/* 소개 */}
      <section
        style={{
          textAlign: 'center',
          padding: 'clamp(48px, 8vw, 88px) 16px',
          background: colors.orangeTint,
          border: `1px solid ${colors.orange50}`,
          borderRadius: 18,
        }}
      >
        <span
          style={{
            display: 'inline-block',
            background: colors.orange,
            color: colors.black,
            fontSize: 15,
            fontWeight: 700,
            padding: '4px 16px',
            borderRadius: 980,
          }}
        >
          팀 {TEAM_NAME}
        </span>
        <h1
          style={{
            fontSize: 'clamp(44px, 9vw, 80px)',
            fontWeight: 700,
            letterSpacing: '-0.03em',
            lineHeight: 1.05,
            margin: '20px 0 0',
            color: colors.black,
          }}
        >
          Spec<span style={{ color: colors.orange }}>ton</span>
        </h1>
        <div
          style={{ width: 64, height: 4, background: colors.orange, borderRadius: 2, margin: '20px auto' }}
        />
        <p style={{ fontSize: 'clamp(19px, 3vw, 26px)', fontWeight: 600, color: colors.ink, margin: 0 }}>
          요구사항 정의서에서 설계 산출물까지
        </p>
        <p style={{ fontSize: 17, color: colors.inkMuted, margin: '8px 0 32px' }}>
          문서를 올리면 기능 명세와 데이터베이스 설계를 만들고, 사람이 확인한 결과만 내보냅니다.
        </p>
        <Button type="primary" size="large" onClick={() => navigate('/')}>
          시작하기
        </Button>
      </section>

      {/* 흐름 세 단계: 오렌지 100 → 70 → 50 */}
      <section
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 16,
        }}
      >
        {FLOW.map((step, i) => (
          <div key={step.title} style={{ background: step.bg, borderRadius: 18, padding: 28 }}>
            <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1, color: colors.black }}>
              {i + 1}
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, margin: '12px 0 8px', color: colors.black }}>
              {step.title}
            </div>
            <div style={{ fontSize: 15, lineHeight: 1.6, color: colors.black }}>{step.text}</div>
          </div>
        ))}
      </section>

      {/* 함께한 곳: 한화 블랙 띠 */}
      <footer
        style={{
          textAlign: 'center',
          background: colors.black,
          borderRadius: 18,
          borderTop: `4px solid ${colors.orange}`,
          padding: '32px 16px',
        }}
      >
        <Flex justify="center" align="center" wrap gap="8px 20px">
          {PARTNERS.map((name, i) => (
            <Flex key={name} align="center" gap={20}>
              {i > 0 && <span style={{ color: colors.orange }}>●</span>}
              <span style={{ fontSize: 16, fontWeight: 600, color: '#fff' }}>{name}</span>
            </Flex>
          ))}
        </Flex>
        <p style={{ fontSize: 12, color: colors.orange70, margin: '16px 0 0' }}>
          © 2026 팀 {TEAM_NAME} · {PROJECT_NAME}
        </p>
      </footer>
    </Flex>
  )
}

export default HomePage
