"""few-shot 예시 로더 (04 문서 "노드 작성 규칙").

`domain_packs/<pack>/examples/<agent>.yaml`을 읽는다. 파일 형식은 여기서 검증하고,
`output`은 노드가 넘긴 LLM 출력 모델로 검증한다. 모양이 틀린 예시는 프롬프트에 넣지 않는다.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from specton.packs.build import DEFAULT_ROOT

AgentId = Annotated[str, StringConstraints(pattern=r"^A0[1-9]$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class ExampleError(ValueError):
    """예시 파일이 없거나 형식이 틀렸다."""


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class _RawExample(_Strict):
    source_id: NonEmpty  # 개발용 세트의 원문 ID (예: INV-003)
    input: NonEmpty | dict[str, Any]  # 노드가 <data>에 넣는 것과 같은 모양
    output: dict[str, Any]


class ExampleFile(_Strict):
    agent: AgentId
    role: NonEmpty
    status: Literal["draft", "approved"]
    examples: tuple[_RawExample, ...] = ()


@dataclass(frozen=True)
class FewShot[OutputT: BaseModel]:
    """검증을 통과한 예시 하나. 프롬프트에는 input → output 대화 쌍으로 들어간다."""

    source_id: str
    input: str | dict[str, Any]
    output: OutputT


def load_example_file(path: Path) -> ExampleFile:
    """파일 형식만 검증한다. output 모양은 load_examples가 출력 모델로 확인한다."""
    if not path.is_file():
        raise ExampleError(f"few-shot 예시 파일이 없습니다: {path}")
    try:
        parsed = ExampleFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise ExampleError(f"{path.name}: 예시 파일 형식이 틀렸습니다\n{exc}") from exc
    if parsed.agent != path.stem:
        raise ExampleError(f"{path.name}: 파일 이름과 agent({parsed.agent})가 다릅니다")
    return parsed


def load_examples[OutputT: BaseModel](
    pack: str, agent: str, output_model: type[OutputT], *, root: Path = DEFAULT_ROOT
) -> tuple[FewShot[OutputT], ...]:
    """팩의 에이전트 예시를 읽어 output을 출력 모델로 검증한 결과를 돌려준다."""
    path = root / pack / "examples" / f"{agent}.yaml"
    return tuple(_validated(e, output_model, path) for e in load_example_file(path).examples)


def _validated[OutputT: BaseModel](
    example: _RawExample, output_model: type[OutputT], path: Path
) -> FewShot[OutputT]:
    try:
        output = output_model.model_validate(example.output)
    except ValidationError as exc:
        model_name = output_model.__name__
        raise ExampleError(
            f"{path.name} {example.source_id}: output이 {model_name}와 맞지 않습니다\n{exc}"
        ) from exc
    return FewShot(source_id=example.source_id, input=example.input, output=output)
