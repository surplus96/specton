// 선 아이콘 몇 개 (모양은 「프로젝트 산출물 웹사이트 디자인」 Figma 시안에서 가져옴). 색은 글자색(currentColor)을 따른다.
// 장식용이라 화면 읽기 프로그램에는 숨긴다. 뜻은 항상 옆 글자로 전한다.
export type IconName = 'file' | 'list' | 'database' | 'code' | 'link' | 'chevron' | 'alert' | 'check'

const PATHS: Record<IconName, string[]> = {
  file: ['M6 3h8l4 4v14H6V3Z', 'M14 3v5h5M9 13h6M9 17h5'],
  list: ['M9 6h11M9 12h11M9 18h11', 'M4 6h.01M4 12h.01M4 18h.01'],
  database: [
    'M4 5c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z',
    'M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7',
  ],
  code: ['m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14'],
  link: ['M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.1 1.1', 'M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1'],
  chevron: ['m9 18 6-6-6-6'],
  alert: ['M12 3 2 20h20L12 3Z', 'M12 10v4M12 17h.01'],
  check: ['M20 6 9 17l-5-5'],
}

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}

export default Icon
