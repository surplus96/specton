/** 받침이 있으면 '을', 없으면 '를' (예: 검토 의견을, 설계 문서를). 한글이 아니면 '을/를' */
export function objectParticle(word: string): string {
  const last = word.trim().slice(-1)
  const code = last.charCodeAt(0) - 0xac00
  if (code < 0 || code > 11171) return '을/를'
  return code % 28 === 0 ? '를' : '을'
}
