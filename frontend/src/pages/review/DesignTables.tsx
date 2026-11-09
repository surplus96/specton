import { Table, Tabs, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import type { DesignAttribute, DesignEntity, DesignFunction, DesignItem, DesignRelationship } from '../../api/viewItems.ts'
import { crudText, dataTypeText, keyText, priorityText, relationText, splitDesign } from './design.ts'

// 설계 결과 표: 기능·엔티티·관계 (/view?section=design). 최종 검토(UI-06)에서 무엇을 승인하는지 보여 준다.
// 결과 작업공간(UI-05)에서도 같은 표를 쓴다. ERD는 8단계(mermaid JS)에서 더한다.
type Props = {
  items: DesignItem[]
  names: Map<string, string>
}

const reqText = (ids: string[]) => ids.join(', ')

function DesignTables({ items, names }: Props) {
  const { functions, entities, relationships } = splitDesign(items)

  if (items.length === 0) {
    return <Typography.Text type="secondary">설계 결과가 아직 없습니다.</Typography.Text>
  }

  const functionColumns: TableColumnsType<DesignFunction> = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: '기능', dataIndex: 'name', width: 140 },
    { title: '설명', dataIndex: 'description' },
    { title: '우선순위', key: 'priority', width: 110, render: (_, f) => priorityText(f) },
    { title: '엔티티 CRUD', key: 'crud', width: 180, render: (_, f) => crudText(f, names) },
    { title: '요구사항', dataIndex: 'req_ids', width: 130, render: reqText },
  ]

  const entityColumns: TableColumnsType<DesignEntity> = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: '엔티티', dataIndex: 'name', width: 140 },
    { title: '설명', dataIndex: 'description' },
    { title: '속성', key: 'count', width: 80, render: (_, e) => `${e.attributes.length}개` },
    { title: '요구사항', dataIndex: 'req_ids', width: 130, render: reqText },
  ]

  const attributeColumns: TableColumnsType<DesignAttribute> = [
    { title: '속성', dataIndex: 'name', width: 140 },
    { title: '타입', key: 'type', width: 130, render: (_, a) => dataTypeText(a) },
    { title: '키', key: 'key', width: 100, render: (_, a) => keyText(a) },
    { title: '빈 값', dataIndex: 'nullable', width: 80, render: (n: boolean) => (n ? '허용' : '불가') },
    { title: '설명', dataIndex: 'description', render: (d: string | null) => d ?? '—' },
  ]

  const relationshipColumns: TableColumnsType<DesignRelationship> = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    {
      title: '관계',
      key: 'pair',
      width: 180,
      render: (_, r) => `${names.get(r.parent) ?? r.parent} → ${names.get(r.child) ?? r.child}`,
    },
    { title: '성격', key: 'kind', width: 160, render: (_, r) => relationText(r) },
    { title: '근거', dataIndex: 'rationale' },
    { title: '요구사항', dataIndex: 'req_ids', width: 130, render: reqText },
  ]

  return (
    <Tabs
      items={[
        {
          key: 'functions',
          label: `기능 ${functions.length}`,
          children: (
            <Table rowKey="id" size="small" pagination={false} columns={functionColumns} dataSource={functions} scroll={{ x: 900 }} />
          ),
        },
        {
          key: 'entities',
          label: `엔티티 ${entities.length}`,
          children: (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              columns={entityColumns}
              dataSource={entities}
              scroll={{ x: 800 }}
              expandable={{
                expandedRowRender: (e) => (
                  <Table rowKey="id" size="small" pagination={false} columns={attributeColumns} dataSource={e.attributes} />
                ),
              }}
            />
          ),
        },
        {
          key: 'relationships',
          label: `관계 ${relationships.length}`,
          children: (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              columns={relationshipColumns}
              dataSource={relationships}
              scroll={{ x: 900 }}
            />
          ),
        },
      ]}
    />
  )
}

export default DesignTables
