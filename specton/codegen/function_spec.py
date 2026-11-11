"""기능 명세서: 설계 상태 → Markdown (#14, docs/10 「출력 규격」, REQ-18).

기능 ID·설명·우선순위와 근거·관련 요구사항·CRUD를 담는다. PDF는 승인 때 #13의 공용 엔진이
이 Markdown을 변환한다 (ADR-0004).

- 문법은 PDF 엔진과 맞춘 것만 쓴다: 제목, 문단, 글머리표, 굵게, 인라인 코드, 파이프 표 (#13 댓글).
  HTML 태그·이미지·각주·셀 안 줄바꿈은 쓰지 않는다. 넓은 CRUD 표는 엔진이 가로 쪽·열 나누기로
  처리한다.
- 초안 표시는 넣지 않는다. 승인본은 같은 바이트를 그대로 쓰므로(export) 초안·승인 구분은
  파일 이름과 PDF가 한다 (docs/06 「산출물」).
- 문서 머리의 문서 정보 칸 이름은 ERD PDF 표지와 같다: run_id·revision·model_hash·pack·pack_version.
- 같은 입력이면 항상 같은 문자열이다 (기능·엔티티는 설계 순서를 따른다).
- 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
"""

from specton.contracts import DesignState
from specton.contracts.base import Crud, PrioritySource
from specton.contracts.design import Function
from specton.model_hash import model_hash

# 문서 정보 표의 (표시 이름, 칸 이름). ERD PDF 표지와 같은 값·같은 이름을 쓴다 (#13·#14 합의)
DOCUMENT_INFO = (
    ("실행 ID", "run_id"),
    ("리비전", "revision"),
    ("모델 해시", "model_hash"),
    ("도메인 팩", "pack"),
    ("팩 버전", "pack_version"),
)
_PRIORITY_SOURCE = {
    PrioritySource.EXPLICIT: "원문 명시",
    PrioritySource.INFERRED: "추정",
}
_CRUD_ORDER = tuple(Crud)
# 글자로 보여야 하는 Markdown 기호. 표 구분자 `|`는 표 칸에서만 이스케이프한다
_MARKDOWN_SIGNS = frozenset("\\*`")


def document_info(design: DesignState) -> dict[str, str]:
    """문서 머리에 넣는 값. 다른 산출물(RTM 등)도 같은 값을 쓴다."""
    return {
        "run_id": design.run_id,
        "revision": str(design.revision),
        "model_hash": model_hash(design),
        "pack": design.versions.pack_id or "",
        "pack_version": design.versions.pack_version or "",
    }


def render_function_spec(design: DesignState) -> str:
    """기능 명세서 Markdown. 기능이 없으면 만들지 않는다."""
    if not design.functions:
        raise ValueError("기능 명세서: 기능이 없습니다")
    entities = {e.id: e.name for e in design.entities}
    for function in design.functions:
        for op in function.entity_ops:
            if op.entity_id not in entities:
                raise ValueError(f"{function.id}: 설계에 없는 엔티티를 가리킵니다 ({op.entity_id})")
    info = document_info(design)
    lines = [
        "# 기능 명세서",
        "",
        "## 문서 정보",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        *(f"| {label} (`{key}`) | {_cell(info[key]) or '-'} |" for label, key in DOCUMENT_INFO),
        "",
        "## 기능 목록",
        "",
        "| 기능 ID | 기능명 | 우선순위 | 관련 요구사항 |",
        "|---|---|---|---|",
        *(
            f"| {f.id} | {_cell(f.name)} | {_priority(f)} | {', '.join(f.req_ids)} |"
            for f in design.functions
        ),
        "",
        "## 기능 상세",
    ]
    for function in design.functions:
        lines += ["", *_detail(function, entities)]
    lines += ["", *_handoff(design), "", *_crud_matrix(design)]
    return "\n".join(lines) + "\n"


def _handoff(design: DesignState) -> list[str]:
    """해시에 포함된 요구·질문을 인계한다. 문장 연결을 구현·검증 완료로 표시하지 않는다."""
    if not design.requirements:
        return []
    lines = [
        "## 구현·검증 인계",
        "",
        "요구사항 연결과 SQL 실행 검증은 업무 조건의 구현·시험 완료를 뜻하지 않습니다. "
        "아래 조건의 처리 책임과 인수 시험을 확인해야 합니다. "
        "현재 DDL 생성 범위에는 값 범위 CHECK·권한·트랜잭션 로직이 포함되지 않습니다.",
        "",
    ]
    for req in design.requirements:
        functions = ", ".join(f.id for f in design.functions if req.id in f.req_ids)
        lines += [
            f"### {req.id} 구현 조건",
            "",
            f"- **요구 조건:** {_text(req.text)}",
            f"- **연결 기능:** {functions or '없음 — 시스템 적용 위치·검증 근거 확인 필요'}",
        ]
        for issue in req.quality_issues:
            lines.append(f"- **분석 시 확인사항 (해결 여부 확인 필요):** {_text(issue.message)}")
            if issue.question:
                lines.append(f"- **확인 질문:** {_text(issue.question)}")
    return lines


def _detail(function: Function, entities: dict[str, str]) -> list[str]:
    ops = [f"{_text(entities[op.entity_id])}({_ops(op.operations)})" for op in function.entity_ops]
    return [
        f"### {function.id} {_text(function.name)}",
        "",
        f"- **설명:** {_text(function.description)}",
        f"- **우선순위:** {_priority(function)}",
        f"- **우선순위 근거:** {_text(function.priority_rationale) or '-'}",
        f"- **관련 요구사항:** {', '.join(f'`{r}`' for r in function.req_ids)}",
        f"- **엔티티 조작:** {', '.join(ops) if ops else '없음'}",
    ]


def _crud_matrix(design: DesignState) -> list[str]:
    """기능별·엔티티별 CRUD 표. 칸은 `C R U D` 중 그 기능이 하는 조작이다."""
    lines = ["## CRUD 매트릭스", ""]
    if not design.entities:
        return [*lines, "엔티티가 없습니다."]
    ops = {
        (f.id, op.entity_id): _ops(op.operations) for f in design.functions for op in f.entity_ops
    }
    lines += [
        "| 기능 | " + " | ".join(_cell(e.name) for e in design.entities) + " |",
        "|---|" + "---|" * len(design.entities),
        *(
            f"| {f.id} {_cell(f.name)} | "
            + " | ".join(ops.get((f.id, e.id), "") for e in design.entities)
            + " |"
            for f in design.functions
        ),
    ]
    exemptions = [
        f"- {_text(e.name)}: {x.operation.value} 없음 — {_text(x.reason)}"
        for e in design.entities
        for x in e.crud_exemptions
    ]
    if exemptions:
        lines += ["", "### CRUD 면제", "", *exemptions]
    return lines


def _priority(function: Function) -> str:
    if function.priority is None:
        return "미정"
    return f"{function.priority.value} ({_PRIORITY_SOURCE[function.priority_source]})"


def _ops(operations: tuple[Crud, ...]) -> str:
    return " ".join(op.value for op in _CRUD_ORDER if op in operations)


def _text(value: str | None) -> str:
    """문단·목록 안의 글. 줄바꿈은 공백으로 바꾸고 Markdown 기호를 글자로 이스케이프한다.

    `\\`를 먼저 이스케이프해야 뒤에 붙이는 이스케이프와 섞이지 않는다. `*`·`` ` ``는 굵게·코드로
    잘못 보이지 않게 한다 (#213 리뷰, PDF 엔진도 역슬래시 이스케이프를 글자로 보인다).
    """
    text = " ".join((value or "").split())
    return "".join(f"\\{c}" if c in _MARKDOWN_SIGNS else c for c in text)


def _cell(value: str) -> str:
    """표 칸 글. `_text`에 더해 표 구분자 `|`를 이스케이프한다."""
    return _text(value).replace("|", "\\|")
