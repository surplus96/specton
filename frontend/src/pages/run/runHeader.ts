export function runEyebrow(screen: string, label: string, runId: string, revision: number): string {
  return `${screen} · ${label} · 실행 ${runId.slice(0, 8)} · revision ${revision}`
}
