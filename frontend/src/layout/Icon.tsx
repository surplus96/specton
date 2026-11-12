// 선 아이콘. 색은 글자색(currentColor)을 따른다. 장식용이라 화면 읽기 프로그램에는 숨기고 뜻은 옆 글자로 전한다.
export type IconName =
  | 'file'
  | 'fileUp'
  | 'list'
  | 'database'
  | 'code'
  | 'link'
  | 'chevron'
  | 'chevronDown'
  | 'alert'
  | 'check'
  | 'checkCircle'
  | 'info'
  | 'x'
  | 'plus'
  | 'search'
  | 'history'
  | 'sidebar'
  | 'book'
  | 'arrowRight'
  | 'download'
  | 'menu'
  | 'external'
  | 'clock'
  | 'refresh'
  | 'sun'
  | 'moon'

const PATHS: Record<IconName, string[]> = {
  file: ['M6 3h8l4 4v14H6V3Z', 'M14 3v5h5M9 13h6M9 17h5'],
  fileUp: ['M6 3h8l4 4v14H6V3Z', 'M14 3v5h5', 'M12 17v-6M9.5 13.5 12 11l2.5 2.5'],
  list: ['M9 6h11M9 12h11M9 18h11', 'M4 6h.01M4 12h.01M4 18h.01'],
  database: [
    'M4 5c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z',
    'M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7',
  ],
  code: ['m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14'],
  link: ['M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.1 1.1', 'M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1'],
  chevron: ['m9 18 6-6-6-6'],
  chevronDown: ['m6 9 6 6 6-6'],
  alert: ['M12 3 2 20h20L12 3Z', 'M12 10v4M12 17h.01'],
  check: ['M20 6 9 17l-5-5'],
  checkCircle: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z', 'm8 12 3 3 5-6'],
  info: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z', 'M12 11v5M12 8h.01'],
  x: ['M18 6 6 18M6 6l12 12'],
  plus: ['M12 5v14M5 12h14'],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z', 'm21 21-4.3-4.3'],
  history: ['M3 12a9 9 0 1 0 3-6.7L3 8', 'M3 3v5h5', 'M12 7v5l3 2'],
  sidebar: ['M4 4h16v16H4z', 'M9 4v16'],
  book: ['M2 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H2V5Z', 'M22 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8V5Z'],
  arrowRight: ['M5 12h14M13 6l6 6-6 6'],
  download: ['M12 4v12M7 11l5 5 5-5', 'M5 20h14'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
  external: ['M14 4h6v6M20 4l-9 9', 'M18 14v6H4V6h6'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z', 'M12 7v5l3 2'],
  sun: ['M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z', 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4'],
  moon: ['M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z'],
  refresh: ['M20 11a8 8 0 0 0-14.8-4M4 4v4h4', 'M4 13a8 8 0 0 0 14.8 4M20 20v-4h-4'],
}

function Icon({ name, size = 20, strokeWidth = 1.8 }: { name: IconName; size?: number; strokeWidth?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}

export default Icon
