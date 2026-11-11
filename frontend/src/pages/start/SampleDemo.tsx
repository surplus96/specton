import Icon from '../../layout/Icon.tsx'

// 첫 방문 「작동 과정 · 샘플 재생」 (F안 시안). 실제 실행 데이터가 아니라 가상 예시라는 것을 분명히 적는다.
// 단계가 차례로 채워지는 움직임만 있고(줄어든 동작이면 멈춤), 눌러서 실행되는 버튼은 두지 않는다.
const STEPS = [
  { n: '01', title: '문서 읽기', desc: '행과 열을 읽어 요구사항을 찾아요' },
  { n: '02', title: '요구사항 정리', desc: '요구사항을 나누고 기능 · 비기능으로 분류해요' },
  { n: '03', title: '초안 생성', desc: '기능 명세서 · ERD · DDL · RTM을 만들고, 규칙 검사와 AI 검토를 함께 돌려요' },
  { n: '04', title: '검토와 승인', desc: '사람이 검토하고 최종 승인해요' },
]

const INPUT = [
  ['REQ-F-001', '품목 등록'],
  ['REQ-F-002', '입고 처리'],
  ['REQ-F-003', '출고 처리'],
  ['REQ-F-004', '재고 조회'],
  ['REQ-N-001', '이력 보관'],
  ['REQ-N-002', '접근 권한'],
]

const SORTED: [string, string, boolean][] = [
  ['REQ-F-001', '품목 등록', true],
  ['REQ-F-002', '입고 처리', true],
  ['REQ-F-003', '출고 처리', true],
  ['REQ-N-001', '이력 보관', false],
  ['REQ-N-002', '접근 권한', false],
]

const RTM = [
  ['REQ-F-001', 'F-01', 'item'],
  ['REQ-F-002', 'F-02', 'stock · stock_txn'],
  ['REQ-F-003', 'F-03', 'stock · stock_txn'],
  ['REQ-N-001', '—', 'stock_txn'],
]

function SampleDemo() {
  return (
    <section className="demo" aria-label="작동 과정 샘플 (가상 데이터)">
      <div className="demo__inner">
        <div className="row row--between">
          <div className="row" style={{ gap: 10 }}>
            <span className="dot-lime" aria-hidden="true" style={{ marginRight: 0 }} />
            <span>작동 과정 · 샘플 재생</span>
            <span className="badge badge--dashed" style={{ background: 'transparent', color: 'rgba(243,242,233,.8)', borderColor: 'rgba(243,242,233,.5)' }}>
              샘플 · 가상 데이터
            </span>
          </div>
          <span className="badge" style={{ background: 'transparent', color: 'var(--ivory)', borderColor: 'rgba(243,242,233,.35)', fontSize: 13, padding: '5px 12px' }}>
            <b>확인 받기</b>&nbsp;· 확인할 항목이 있을 때만 멈춤
          </span>
        </div>
        <h2 style={{ margin: 0, fontWeight: 400, fontSize: 'clamp(22px, 2.6vw, 30px)', letterSpacing: '-0.02em' }}>
          샘플 요구사항 정의서가 <strong style={{ fontWeight: 800 }}>설계 초안</strong>이 되는 과정
        </h2>

        <ol className="demo__steps" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {STEPS.map((s) => (
            <li key={s.n} className="demo__step">
              <div className="demo__step-bar">
                <i />
              </div>
              <b>
                <span>{s.n}</span>
                {s.title}
              </b>
              <p>{s.desc}</p>
            </li>
          ))}
        </ol>

        <div className="demo__cols">
          <div className="demo__col">
            <h4>
              <span>
                입력 <small>요구사항정의서.xlsx</small>
              </span>
              <small>6 / 6건</small>
            </h4>
            {INPUT.map(([id, name]) => (
              <div key={id} className="demo__line" style={{ border: 0, padding: '4px 2px' }}>
                <span className="mono" style={{ width: 92, flex: 'none' }}>
                  {id}
                </span>
                <span>{name}</span>
              </div>
            ))}
          </div>
          <div className="demo__col">
            <h4>
              <span>
                정리 <small>요구사항 5건</small>
              </span>
              <small>기능 3 · 비기능 2</small>
            </h4>
            {SORTED.map(([id, name, fr]) => (
              <div key={id} className="demo__line">
                <span className={`demo__chip${fr ? '' : ' demo__chip--ghost'}`}>{fr ? '기능' : '비기능'}</span>
                <span className="mono" style={{ opacity: 0.6 }}>
                  {id}
                </span>
                <span>{name}</span>
              </div>
            ))}
          </div>
          <div className="demo__col">
            <h4>
              <span>
                초안 <small>4종</small>
              </span>
              <small>4 / 4</small>
            </h4>
            <div className="row" style={{ gap: 6 }}>
              {['기능 명세', 'ERD', 'DDL', 'RTM'].map((t) => (
                <span key={t} className="demo__line" style={{ flex: '1 1 0', justifyContent: 'space-between', fontWeight: 600 }}>
                  <span>{t}</span>
                  <Icon name="check" size={14} />
                </span>
              ))}
            </div>
            <div style={{ fontSize: 13, display: 'grid', gap: 6, marginTop: 6 }}>
              <div className="mono" style={{ opacity: 0.55, fontSize: 11, letterSpacing: '0.1em' }}>
                RTM · EXCEL · CSV
              </div>
              {RTM.map(([req, fn, table]) => (
                <div key={req} style={{ display: 'grid', gridTemplateColumns: '1.2fr .5fr 1.2fr', gap: 8, borderBottom: '1px solid rgba(243,242,233,.12)', paddingBottom: 4 }}>
                  <span className="mono">{req}</span>
                  <span style={{ color: fn === '—' ? undefined : 'var(--lime)' }}>{fn}</span>
                  <span style={{ opacity: 0.85 }}>{table}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="demo__foot">
        <span>
          <span className="dot-lime" aria-hidden="true" />
          설계 초안 4종을 만들었어요. 검사 결과와 AI 검토 의견을 확인하고 승인해 주세요
        </span>
        <span className="row" style={{ gap: 12 }}>
          <span style={{ opacity: 0.7, fontSize: 14 }}>차단 오류가 없을 때 사람이 승인해요</span>
          <span className="badge badge--lime" style={{ fontSize: 14, padding: '6px 12px' }}>
            승인 대기
          </span>
        </span>
      </div>
    </section>
  )
}

export default SampleDemo
