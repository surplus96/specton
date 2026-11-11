import { revisionText } from '../runMeta.ts'

export function runEyebrow(screen: string, label: string, revision: number): string {
  return `${screen} · ${label} · ${revisionText(revision)}`
}
