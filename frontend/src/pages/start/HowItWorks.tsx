// 첫 방문 안내 「작동 과정」 (시안): 접을 수 있는 칸 하나에 세 단계를 나란히 보인다. 움직이는 샘플은 쓰지 않는다.
// 02 진행 방식은 지금 동작 그대로 쓴다: 확인할 항목이 있을 때만 멈추고(ADR-0015), 최종 승인은 늘 사람이 한다.
const STEPS = [
  { n: '01', title: '파일 선택', desc: 'Excel · CSV · HWP · HWPX 요구사항 문서를 끌어다 놓거나 선택해요' },
  { n: '02', title: '진행 방식', desc: '확인할 항목이 있을 때만 멈추고, 확인하면 다음 단계로 넘어가요' },
  { n: '03', title: '확인과 승인', desc: '기능 명세서 · ERD · DDL · RTM 초안을 사람이 확인하고 승인해요' },
]

function HowItWorks() {
  return (
    <details className="how" open>
      <summary className="how__head">
        <span>작동 과정</span>
        <span className="how__chevron" aria-hidden="true" />
      </summary>
      <ol className="how__steps">
        {STEPS.map((s) => (
          <li key={s.n} className="how__step">
            <span className="how__num">{s.n}</span>
            <strong className="how__title">{s.title}</strong>
            <p className="how__desc">{s.desc}</p>
          </li>
        ))}
      </ol>
    </details>
  )
}

export default HowItWorks
