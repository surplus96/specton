// view.artifacts의 기존 SQL 검증 요약을 읽는다. 다른 revision·잘못된 값은 통과로 보이지 않는다.
export type SqlReview = {
  status: 'missing' | 'unverified' | 'passed' | 'failed' | 'error'
  validatedAt: string | null
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function sqlReview(artifacts: readonly unknown[] | undefined, revision: number): SqlReview {
  const sql = (artifacts ?? []).filter(
    (a): a is Record<string, unknown> => record(a) && a.kind === 'ddl' && a.file_format === 'sql' && a.revision === revision,
  )
  if (sql.length === 0) return { status: 'missing', validatedAt: null }
  if (sql.length !== 1 || !record(sql[0].validation)) return { status: 'unverified', validatedAt: null }
  const { status, validated_at } = sql[0].validation
  if (status !== 'passed' && status !== 'failed' && status !== 'error' && status !== 'unverified') {
    return { status: 'unverified', validatedAt: null }
  }
  return {
    status,
    validatedAt: typeof validated_at === 'string' && Number.isFinite(Date.parse(validated_at)) ? validated_at : null,
  }
}
