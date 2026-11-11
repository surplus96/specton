import { useNavigate } from 'react-router'
import Icon from '../layout/Icon.tsx'
import Button from '../ui/Button.tsx'
import { FORMATS_LABEL } from './upload/rules.ts'

// Docs: 서비스 안내 · 팀 소개 (/about). 예전 첫 화면(팀 소개)의 내용을 그대로 옮겼다.
// 읽는 순서(디자인 시스템 7 「서비스 자세히 보기」): 서비스 정의 → 작업 흐름 → 산출물 → 사람의 확인 → 팀
const TEAM_NAME = '설계로'
const PARTNERS = ['한화내일아카데미', '한화시스템', '고용노동부']

const TEAM = [
  { name: '최태영', role: '실행 제어 · 통합', leader: true },
  { name: '김희영', role: '입력 · 분석 · 평가' },
  { name: '박성진', role: '기능 · API · 저장' },
  { name: '김유경', role: '데이터 모델 · 검증' },
  { name: '김순재', role: '관계 · 시각화 · 웹' },
]

const FLOW = [
  { n: '1', title: '실행 시작', desc: '파일 올리고 실행', kind: '' },
  { n: '2', title: '추출 확인', desc: '확인할 항목이 있을 때만', kind: 'cond' },
  { n: '3', title: '분석 확인', desc: '경고·질문·분할이 있을 때만', kind: 'cond' },
  { n: '4', title: '설계 진행', desc: '멈추지 않음', kind: '' },
  { n: '5', title: '결과 작업공간', desc: '기능·ERD·DDL·RTM·검토', kind: '' },
  { n: '6', title: '최종 검토', desc: '항상 사람이 누름', kind: 'human' },
  { n: '7', title: '다운로드', desc: '형식별 내려받기', kind: '' },
]

const OUTPUTS = [
  ['기능 명세서', 'Markdown · PDF(승인 후)'],
  ['ERD', 'Mermaid · PDF(승인 후)'],
  ['DDL', 'PostgreSQL SQL · 샌드박스 DB에서 검증'],
  ['RTM 추적표', 'Excel · CSV'],
]

function AboutPage() {
  const navigate = useNavigate()
  return (
    <div className="stack-lg screen">
      <header>
        <p className="eyebrow">Docs · 서비스 안내</p>
        <h1 className="hero">
          요구사항에서 <strong>설계 초안</strong>까지
        </h1>
        <p className="muted" style={{ fontSize: 18, margin: '18px 0 28px', maxWidth: 720 }}>
          요구사항 정의서({FORMATS_LABEL})를 올리면 기능 명세서 · ERD · DDL · RTM 초안을 만들어요. 사람이 확인한 결과만 내보내요.
        </p>
        <Button size="lg" onClick={() => navigate('/')} iconEnd={<Icon name="arrowRight" size={18} />}>
          새 작업 시작
        </Button>
      </header>

      <section>
        <h2 className="section-title">작업 흐름</h2>
        <div className="flow7">
          {FLOW.map((f) => (
            <div key={f.n} className={f.kind}>
              <span className="mono subtle">{f.n}</span>
              <b>{f.title}</b>
              <span className="muted">{f.desc}</span>
            </div>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 14, marginTop: 12 }}>
          점선은 필요할 때만 멈추는 단계, 라임은 사람이 결정하는 단계예요. 수정 요청을 보내면 다시 설계해 새 revision이 생겨요.
        </p>
      </section>

      <section>
        <h2 className="section-title">산출물</h2>
        <div className="work-grid">
          {OUTPUTS.map(([name, desc]) => (
            <div key={name} className="card">
              <div className="h3">{name}</div>
              <div className="muted" style={{ marginTop: 4 }}>
                {desc}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="section-title">사람의 확인</h2>
        <div className="card card--soft stack-sm">
          <p style={{ margin: 0 }}>AI는 판단만 해요. ID 부여 · SQL · ERD 그림 · RTM 연결은 코드가 만들어요.</p>
          <p style={{ margin: 0 }}>차단 오류가 남아 있으면 승인할 수 없고, 승인은 항상 사람이 직접 눌러요.</p>
        </div>
      </section>

      <section aria-label="팀 소개">
        <h2 className="section-title">팀 {TEAM_NAME}</h2>
        <div className="team">
          {TEAM.map((p) => (
            <div key={p.name} className={`card${p.leader ? ' card--strong' : ''}`}>
              <div className="h3">
                {p.name}
                {p.leader && (
                  <span className="badge badge--lime" style={{ marginLeft: 8 }}>
                    팀장
                  </span>
                )}
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                {p.role}
              </div>
            </div>
          ))}
        </div>
      </section>

      <footer className="row row--between muted" style={{ borderTop: '1px solid var(--line)', paddingTop: 20, fontSize: 14 }}>
        <span>{PARTNERS.join(' · ')}</span>
        <span>© 2026 팀 {TEAM_NAME} · Specton</span>
      </footer>
    </div>
  )
}

export default AboutPage
