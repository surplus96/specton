"""ERD·PDF 규모 실측용 시험 모델 (#13, ADR-0004 「PDF 출력 실측」).

재고 팩 용어로 만든 설계를 실제 정리 코드(`normalize_from_state`)에 통과시킨다.
2026-11-08 실측(테이블 20 · FK 25 · 관계 24, N:M 1, 영역 기준정보 7 · 수불 7 · 재고 이력 6)과
같은 규모로 다시 만든 모델이다. 그때의 모델 파일은 남아 있지 않아 같은 모델은 아니다.

- 이름은 모두 재고 팩 사전에서 물리명이 풀리는 것만 쓴다(「출고」는 아직 팩에 없어 쓰지 않는다).
- 엔티티 19개 + N:M(품목·거래처) 연결 테이블 1개 = 테이블 20개.
- 자기참조 1개(품목분류의 상위 분류)를 넣었다(11/8에는 정리 코드가 막아 뺐다, #166 뒤 가능).
- 영역은 팩의 `erd_areas.yaml`(#199)로 나눈다.

`build_scale_model()`은 LLM·DB·Mermaid 없이 돈다. 시험(`test_pdf_scale.py`)이 쓴다.
"""

from __future__ import annotations

from typing import Any

from specton.codegen.erd_areas import ErdArea, pack_areas
from specton.codegen.model import Normalized
from specton.codegen.naming import DEFAULT_PACK_ROOT
from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.contracts.normalized import NormalizedModel
from specton.contracts.state import VersionInfo
from specton.packs.build import read_yaml

PACK = "inventory"
REQ = "REQ-01"


def _attr(name: str, data_type: str, *, key: bool = False, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"name": name, "data_type": data_type, "req_ids": [REQ]}
    if key:
        data.update(is_key=True, nullable=False)
    return {**data, **extra}


def _vc(name: str, length: int, **extra: Any) -> dict[str, Any]:
    return _attr(name, "varchar", length=length, **extra)


def _qty(name: str) -> dict[str, Any]:
    return _attr(name, "numeric", precision=12, scale=3)


def _amt(name: str) -> dict[str, Any]:
    return _attr(name, "numeric", precision=15, scale=2)


def _sn() -> dict[str, Any]:
    return _attr("일련번호", "integer", key=True)


# (엔티티 ID 꼬리, 이름, 속성들). 식별 관계의 자식은 부모 키를 물려받으므로 자기 키만 적는다.
ENTITIES: tuple[tuple[str, str, tuple[dict[str, Any], ...]], ...] = (
    # 기준정보 6 (+ 연결 테이블 품목거래처 1 = 7)
    ("wh", "창고", (_vc("창고코드", 10, key=True), _vc("창고명", 100), _vc("주소", 200),
                   _attr("창고구분", "char", length=2), _attr("사용여부", "char", length=1))),
    ("loc", "보관위치", (_vc("위치코드", 10, key=True), _vc("위치명", 100),
                       _attr("위치구분", "char", length=2))),
    ("item", "품목", (_vc("품목코드", 20, key=True), _vc("품목명", 100), _qty("안전재고수량"),
                     _amt("품목단가"), _attr("사용여부", "char", length=1))),
    ("cls", "품목분류", (_vc("분류코드", 10, key=True), _vc("분류명", 100), _vc("설명", 200))),
    ("cnpt", "거래처", (_vc("거래처코드", 10, key=True), _vc("거래처명", 100),
                       _vc("사업자등록번호", 10, is_unique=True, nullable=False),
                       _vc("전화번호", 20), _vc("주소", 200))),
    ("unit", "단위", (_vc("단위코드", 10, key=True), _vc("단위명", 50))),
    # 수불 7
    ("req", "입고요청", (_vc("입고요청번호", 20, key=True), _attr("요청일자", "date"),
                       _qty("요청수량"), _attr("요청상태", "char", length=2))),
    ("rc", "입고", (_vc("입고번호", 20, key=True), _attr("입고일자", "date"),
                   _attr("입고상태", "char", length=2))),
    ("rcl", "입고내역", (_sn(), _qty("입고수량"), _amt("입고단가"))),
    ("mv", "재고이동", (_vc("이동번호", 20, key=True), _attr("이동일자", "date"),
                       _vc("이동사유", 200))),
    ("mvl", "재고이동내역", (_sn(), _qty("이동수량"))),
    ("dl", "재고거래", (_vc("거래번호", 20, key=True), _attr("거래일자", "date"))),
    ("dll", "재고거래내역", (_sn(), _qty("거래수량"), _amt("거래단가"))),
    # 재고 이력 6
    ("stk", "창고재고", (_qty("재고수량"), _amt("재고금액"))),
    ("his", "재고이력", (_sn(), _attr("이력일시", "timestamp"), _attr("이력구분", "char", length=2),
                       _qty("재고수량"))),
    ("ac", "재고실사", (_vc("실사번호", 20, key=True), _attr("실사일자", "date"))),
    ("acl", "재고실사내역", (_sn(), _qty("재고수량"), _qty("실사수량"))),
    ("aj", "재고조정", (_vc("조정번호", 20, key=True), _attr("조정일자", "date"), _qty("조정수량"),
                       _vc("조정사유", 200))),
    ("lot", "로트", (_vc("로트번호", 30, key=True), _attr("입고일자", "date"), _qty("재고수량"))),
)  # fmt: skip

# (부모 꼬리, 자식 꼬리, 추가 값). 관계 24개: 1:N 22 · 자기참조 1 · N:M 1 → FK 25개.
RELATIONSHIPS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("cls", "item", {}),
    ("cls", "cls", {"optional": True}),  # 상위 분류 (자기참조)
    ("unit", "item", {}),
    ("wh", "loc", {"identifying": True}),
    ("item", "cnpt", {"cardinality": "N:M", "optional": True}),  # 품목거래처
    ("cnpt", "req", {}),
    ("item", "req", {}),
    ("req", "rc", {"optional": True}),
    ("cnpt", "rc", {}),
    ("wh", "rc", {}),
    ("rc", "rcl", {"identifying": True}),
    ("item", "rcl", {}),
    ("wh", "mv", {}),
    ("mv", "mvl", {"identifying": True}),
    ("item", "mvl", {}),
    ("dl", "dll", {"identifying": True}),
    ("item", "dll", {}),
    ("wh", "stk", {"identifying": True}),
    ("item", "stk", {"identifying": True}),
    ("stk", "his", {"identifying": True}),
    ("wh", "ac", {}),
    ("ac", "acl", {"identifying": True}),
    ("stk", "aj", {}),
    ("item", "lot", {}),
)


def scale_design() -> DesignState:
    """정리 전 설계(A03·A04 출력에 해당)."""
    entities = []
    for tail, name, attrs in ENTITIES:
        numbered = [{"id": f"ATTR-{tail}-{i}", **a} for i, a in enumerate(attrs, start=1)]
        entities.append(
            Entity.model_validate(
                {
                    "id": f"ENT-{tail}",
                    "pack": PACK,
                    "name": name,
                    "description": name,
                    "attributes": numbered,
                    "req_ids": [REQ],
                }
            )
        )
    relationships = [
        Relationship.model_validate(
            {
                "id": f"REL-{i:02d}",
                "parent": f"ENT-{parent}",
                "child": f"ENT-{child}",
                "cardinality": "1:N",
                "optional": False,
                "identifying": False,
                "rationale": '"재고를 관리한다." 시험 모델 관계.',
                "req_ids": [REQ],
                **extra,
            }
        )
        for i, (parent, child, extra) in enumerate(RELATIONSHIPS, start=1)
    ]
    return DesignState(
        run_id="run-scale",
        versions=VersionInfo(
            pack_id=PACK,
            pack_version=str(read_yaml(DEFAULT_PACK_ROOT / PACK / "manifest.yaml")["version"]),
        ),
        requirements=[
            Requirement(
                id=REQ,
                source_ref={"file_format": "csv", "row": 2},
                text="재고를 관리한다.",
                draft_text="재고를 관리한다.",
                type="FR",
                analysis_version=1,
            )
        ],
        entities=entities,
        relationships=relationships,
    )


def build_scale_model() -> tuple[NormalizedModel, tuple[Relationship, ...], tuple[ErdArea, ...]]:
    """정리한 모델, 관계, 팩 영역. 정리에 실패하면 이유와 함께 멈춘다."""
    design = scale_design()
    result = normalize_from_state({"design": design})
    if not isinstance(result, Normalized):
        raise AssertionError(f"시험 모델 정리 실패: {result}")
    return result.model, tuple(design.relationships), pack_areas(PACK)
