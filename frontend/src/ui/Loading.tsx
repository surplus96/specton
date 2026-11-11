// 불러오는 중 표시. 가짜 진행률 없이 지금 하는 일만 글자로 적는다.
function Loading({ text = '불러오는 중이에요' }: { text?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spin" aria-hidden="true" />
      <span>{text}</span>
    </div>
  )
}

export default Loading
