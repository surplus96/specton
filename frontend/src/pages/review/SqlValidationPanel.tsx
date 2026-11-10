import { Alert } from 'antd'
import type { SqlReview } from './sqlValidation.ts'

const TITLE: Record<SqlReview['status'], string> = {
  passed: 'SQL 검증 통과',
  failed: 'SQL 검증 실패',
  error: 'SQL 검증 실행 오류',
  unverified: 'SQL 미검증',
  missing: 'SQL 산출물 없음',
}

export default function SqlValidationPanel({ result }: { result: SqlReview }) {
  const passed = result.status === 'passed'
  return (
    <section aria-label="SQL 검증 상태">
      <Alert
        type={passed ? 'success' : result.status === 'failed' || result.status === 'error' ? 'error' : 'warning'}
        showIcon
        title={TITLE[result.status]}
        description={
          <>
            <div>
              {passed
                ? '현재 revision의 SQL 검증 결과입니다. 승인할 때 서버가 최신 결과를 다시 확인합니다.'
                : 'SQL 검증 통과를 확인할 수 없습니다. 필수 검증 조건을 충족하지 못하면 승인할 수 없습니다. 수정 요청 또는 보류를 선택할 수 있습니다.'}
            </div>
            {result.validatedAt && <div>검증 시각: {new Date(result.validatedAt).toLocaleString('ko-KR')}</div>}
          </>
        }
      />
    </section>
  )
}
