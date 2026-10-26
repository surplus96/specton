"""설정형 리뷰어의 관점 설정 (04 문서, ADR-0008).

관점(A05~A08)마다 `perspectives/<reviewer_id>.yaml` 파일 하나를 둔다.
파일을 추가하면 리뷰어 노드가 그 관점을 실행한다.
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

PERSPECTIVES_DIR = Path(__file__).parent / "perspectives"

# 리뷰어에게 보여 줄 DesignState 부분. 관점마다 필요한 것만 골라 토큰을 아낀다.
InputSection = Literal["requirements", "functions", "entities", "relationships"]
ReviewerId = Annotated[str, StringConstraints(pattern=r"^A\d{2}$")]
Line = Annotated[str, StringConstraints(min_length=1)]


class PerspectiveError(ValueError):
    """관점 설정 파일이 없거나 형식이 틀렸다."""


class Perspective(BaseModel):
    """검토 관점 하나의 설정. 프롬프트·체크리스트·입력 선택·오탐 기준을 담는다."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    reviewer_id: ReviewerId
    name: Line
    prompt_version: Line
    instructions: Line
    checklist: tuple[Line, ...] = Field(min_length=1)
    inputs: tuple[InputSection, ...] = Field(min_length=1)
    false_positive_guards: tuple[Line, ...] = Field(min_length=1)


def load_perspective(path: Path) -> Perspective:
    try:
        perspective = Perspective.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise PerspectiveError(f"{path.name}: 관점 설정 형식이 틀렸습니다\n{exc}") from exc
    if perspective.reviewer_id != path.stem:
        raise PerspectiveError(
            f"{path.name}: 파일 이름과 reviewer_id({perspective.reviewer_id})가 다릅니다"
        )
    return perspective


def load_perspectives(directory: Path = PERSPECTIVES_DIR) -> tuple[Perspective, ...]:
    """디렉터리의 관점 설정을 reviewer_id 순서로 모두 읽는다."""
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise PerspectiveError(f"관점 설정 파일이 없습니다: {directory}")
    return tuple(load_perspective(path) for path in paths)
