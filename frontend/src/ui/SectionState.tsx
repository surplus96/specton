import { errorMessage } from '../api/errors.ts'
import Button from './Button.tsx'
import Loading from './Loading.tsx'
import Notice from './Notice.tsx'
import { objectParticle } from './particle.ts'
export default function SectionState({ title, error, loading, reload }: { title: string; error: unknown; loading: boolean; reload: () => void }) {
  if (error) return <Notice kind="error" title={`${title}: ${errorMessage(error)}`} action={<Button variant="secondary" size="sm" onClick={reload}>다시 불러오기</Button>} />
  if (loading) return <Loading text={`${title}${objectParticle(title)} 불러오는 중이에요`} />
  return null
}
