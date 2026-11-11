import type { RunStatus } from '../../api/types.ts'
import { STATUS_LABEL } from '../workspace/rules.ts'
import { runEyebrow } from './runHeader.ts'

// 작업 화면 머리글: 화면 이름 · 파일 이름 · n차 설계안 · 상태. 실행 ID는 화면에 표시하지 않는다.
export default function RunEyebrow({ screen, label, run }: { screen: string; label: string; run: Pick<RunStatus, 'run_id' | 'revision' | 'status'> }) {
  return (
    <span>
      {runEyebrow(screen, label, run.revision)} ·{' '}
      {run.status === 'completed' ? '승인 완료' : run.status === 'exporting' ? '승인 후 내보내기' : STATUS_LABEL[run.status]}
    </span>
  )
}
