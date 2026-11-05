"""그래프 상태에서 모델 정리를 부르는 연결 함수 (#12 → #17). **그래프 연결은 R1이 한다.**

R1의 설계 노드(#121 `agent_nodes.py`)처럼 상태에서 입력을 꺼내 정리하고 결과를 돌려준다.
상태에 결과를 넣을 칸(`GraphState`·`DesignState`)이 아직 없어서, 여기서는 노드 모양
(`{"칸 이름": 값}`)으로 감싸지 않는다. 그래프에 없는 칸 이름을 돌려주면 LangGraph가 오류 없이
버리기 때문이다. 칸이 생기면 R1이 `lambda state: {"<칸>": normalize_from_state(state)}`처럼 감싼다.

- 팩은 실행기가 첫 상태에 넣은 `versions.pack_id`·`pack_version`을 쓴다 (#121). 둘 중 하나라도
  없으면 실행 오류(`ValueError`)로 멈춘다. 버전을 모르는 실행을 지금 팩 파일 버전으로
  정리하지 않는다.
- 기록된 팩 버전과 지금 팩 파일 버전이 다르면 정리하지 않고 문제로 돌려준다. 다른 사전으로
  정리하면 같은 입력이라도 결과가 달라지기 때문이다.
- 팩 파일을 읽지 못하거나 명명 규칙을 해석할 수 없으면 예외가 그대로 올라간다 (실행 오류).
- 입력 상태는 바꾸지 않는다. 이 모듈은 LLM client를 import하지 않는다.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.codegen.model import NormalizeFailed, NormalizeResult, ProblemCode, problem
from specton.codegen.naming import DEFAULT_PACK_ROOT, load_naming_rules, load_pack_lexicon
from specton.codegen.normalize import PackRef, normalize
from specton.contracts import DesignState
from specton.packs.build import read_yaml


def normalize_from_state(
    state: Mapping[str, Any], *, root: Path = DEFAULT_PACK_ROOT
) -> NormalizeResult:
    """그래프 상태의 `design`을 정리한다.

    성공이면 `Normalized`, 정리할 수 없으면 `NormalizeFailed`를 돌려준다.
    """
    design = state["design"]
    if not isinstance(design, DesignState):
        raise TypeError("모델 정리: 상태의 design이 DesignState가 아닙니다")
    return normalize_design(design, root=root)


def normalize_design(design: DesignState, *, root: Path = DEFAULT_PACK_ROOT) -> NormalizeResult:
    """설계 상태를 실행에 기록된 팩으로 정리한다."""
    pack = design.versions.pack_id
    if pack is None:
        # 설계 노드(#121)와 같은 처리: 팩 없이 부르면 실행 오류다
        raise ValueError("모델 정리: 실행의 팩이 정해지지 않았습니다")
    recorded = design.versions.pack_version
    if recorded is None:
        # 실행 때 어떤 버전이었는지 모르는 상태를 지금 팩 파일 버전으로 메우지 않는다
        raise ValueError(f"모델 정리: 실행에 기록된 팩 {pack}의 버전이 없습니다")
    current = str(read_yaml(root / pack / "manifest.yaml")["version"])
    if recorded != current:
        return NormalizeFailed(
            problems=(
                problem(
                    ProblemCode.PACK_MISMATCH,
                    "versions.pack_version",
                    f"실행에 기록된 팩 {pack} {recorded} ≠ 지금 팩 파일 {current}",
                ),
            )
        )
    return normalize(
        design,
        pack=PackRef(pack, recorded),
        lexicon=load_pack_lexicon(pack, root),
        rules=load_naming_rules(root),
    )
