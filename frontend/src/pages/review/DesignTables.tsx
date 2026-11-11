import { useState } from 'react'
import type { DesignAttribute, DesignEntity, DesignFunction, DesignItem, DesignRelationship } from '../../api/viewItems.ts'
import DataTable from '../../ui/DataTable.tsx'
import Segmented from '../../ui/Segmented.tsx'
import { crudText, dataTypeText, keyText, priorityText, relationText, splitDesign } from './design.ts'

// 설계 결과 표: 기능·엔티티·관계 (/view?section=design). 최종 검토(UI-06)와 결과 작업공간(UI-05)이 같이 쓴다.
type Props = {
  items: DesignItem[]
  names: Map<string, string>
}

type Part = 'functions' | 'entities' | 'relationships'

const reqText = (ids: string[]) => (ids.length ? ids.join(', ') : '—')

function AttributeTable({ entity }: { entity: DesignEntity }) {
  return (
    <DataTable<DesignAttribute>
      label={`${entity.name} 속성`}
      rows={entity.attributes}
      rowKey={(a) => a.id}
      minWidth={640}
      empty="속성이 없어요."
      columns={[
        { key: 'name', title: '속성', width: 160, render: (a) => a.name },
        { key: 'type', title: '타입', width: 140, render: (a) => <span className="mono">{dataTypeText(a)}</span> },
        { key: 'key', title: '키', width: 110, render: (a) => keyText(a) },
        { key: 'null', title: '빈 값', width: 80, render: (a) => (a.nullable ? '허용' : '불가') },
        { key: 'desc', title: '설명', render: (a) => a.description ?? '—' },
      ]}
    />
  )
}

function DesignTables({ items, names }: Props) {
  const [part, setPart] = useState<Part>('functions')
  const { functions, entities, relationships } = splitDesign(items)
  if (items.length === 0) return <div className="card empty">설계 결과가 아직 없어요.</div>

  return (
    <div className="stack-sm" style={{ gap: 14 }}>
      <Segmented<Part>
        label="설계 결과 종류"
        size="sm"
        value={part}
        onChange={setPart}
        options={[
          { value: 'functions', label: `기능 ${functions.length}` },
          { value: 'entities', label: `엔티티 ${entities.length}` },
          { value: 'relationships', label: `관계 ${relationships.length}` },
        ]}
      />
      {part === 'functions' && (
        <DataTable<DesignFunction>
          label="기능"
          rows={functions}
          rowKey={(f) => f.id}
          minWidth={900}
          empty="기능이 없어요."
          columns={[
            {
              key: 'name',
              title: '기능',
              width: 170,
              render: (f) => (
                <div className="stack-sm" style={{ gap: 2 }}>
                  <strong>{f.name}</strong>
                  <span className="subtle mono" style={{ fontSize: 12 }}>{f.id}</span>
                </div>
              ),
            },
            { key: 'desc', title: '설명', render: (f) => f.description },
            { key: 'priority', title: '우선순위', width: 110, render: (f) => priorityText(f) },
            { key: 'crud', title: '쓰는 테이블 (만들기·조회·수정·삭제)', width: 190, render: (f) => crudText(f, names) },
            { key: 'req', title: '근거 요구사항', width: 140, render: (f) => <span className="mono">{reqText(f.req_ids)}</span> },
          ]}
        />
      )}
      {part === 'entities' && (
        <DataTable<DesignEntity>
          label="엔티티"
          rows={entities}
          rowKey={(e) => e.id}
          minWidth={820}
          empty="엔티티가 없어요."
          expand={(e) => <AttributeTable entity={e} />}
          expandLabel={(e, open) => `${e.name} 속성 ${open ? '접기' : '펼치기'}`}
          columns={[
            {
              key: 'name',
              title: '엔티티',
              width: 170,
              render: (e) => (
                <div className="stack-sm" style={{ gap: 2 }}>
                  <strong>{e.name}</strong>
                  <span className="subtle mono" style={{ fontSize: 12 }}>{e.id}</span>
                </div>
              ),
            },
            { key: 'desc', title: '설명', render: (e) => e.description },
            { key: 'count', title: '속성', width: 80, render: (e) => `${e.attributes.length}개` },
            { key: 'req', title: '근거 요구사항', width: 140, render: (e) => <span className="mono">{reqText(e.req_ids)}</span> },
          ]}
        />
      )}
      {part === 'relationships' && (
        <DataTable<DesignRelationship>
          label="관계"
          rows={relationships}
          rowKey={(r) => r.id}
          minWidth={900}
          empty="관계가 없어요."
          columns={[
            {
              key: 'pair',
              title: '관계',
              width: 210,
              render: (r) => (
                <div className="stack-sm" style={{ gap: 2 }}>
                  <strong>{names.get(r.parent) ?? r.parent} → {names.get(r.child) ?? r.child}</strong>
                  <span className="subtle mono" style={{ fontSize: 12 }}>{r.id}</span>
                </div>
              ),
            },
            { key: 'kind', title: '성격', width: 170, render: (r) => relationText(r) },
            { key: 'why', title: '근거', render: (r) => r.rationale },
            { key: 'req', title: '근거 요구사항', width: 140, render: (r) => <span className="mono">{reqText(r.req_ids)}</span> },
          ]}
        />
      )}
    </div>
  )
}

export default DesignTables
