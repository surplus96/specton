from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from specton.packs.build import DEFAULT_ROOT
from specton.packs.examples import ExampleError, load_example_file, load_examples

REPO_ROOT = Path(__file__).resolve().parents[2]


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str


HEADER = "agent: A02\nrole: function_design\nstatus: draft\n"


def write_examples(root: Path, body: str, *, pack: str = "inventory", agent: str = "A02") -> Path:
    path = root / pack / "examples" / f"{agent}.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_loads_examples_validated_by_the_output_model(tmp_path: Path) -> None:
    write_examples(
        tmp_path,
        "examples:\n- source_id: INV-003\n  input: 입고를 등록한다\n  output: {label: FR}\n",
    )

    examples = load_examples("inventory", "A02", Label, root=tmp_path)

    assert [(e.source_id, e.input, e.output) for e in examples] == [
        ("INV-003", "입고를 등록한다", Label(label="FR"))
    ]


def test_structured_input_is_kept(tmp_path: Path) -> None:
    write_examples(
        tmp_path,
        "examples:\n"
        "- source_id: INV-003\n  input: {requirements: [REQ-01]}\n  output: {label: FR}\n",
    )

    (example,) = load_examples("inventory", "A02", Label, root=tmp_path)

    assert example.input == {"requirements": ["REQ-01"]}


def test_output_that_breaks_the_model_names_the_example(tmp_path: Path) -> None:
    write_examples(
        tmp_path,
        "examples:\n- source_id: INV-007\n  input: x\n  output: {label: FR, check: '> 0'}\n",
    )

    with pytest.raises(ExampleError, match="INV-007"):
        load_examples("inventory", "A02", Label, root=tmp_path)


@pytest.mark.parametrize(
    "body",
    [
        "examples:\n- input: x\n  output: {label: FR}\n",
        "examples: []\nextra: 1\n",
        "examples:\n- source_id: INV-001\n  input: ''\n  output: {label: FR}\n",
    ],
)
def test_malformed_file_is_rejected_with_its_name(tmp_path: Path, body: str) -> None:
    write_examples(tmp_path, body)

    with pytest.raises(ExampleError, match=r"A02\.yaml"):
        load_examples("inventory", "A02", Label, root=tmp_path)


def test_agent_must_match_file_name(tmp_path: Path) -> None:
    path = tmp_path / "inventory" / "examples" / "A03.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + "examples: []\n", encoding="utf-8")

    with pytest.raises(ExampleError, match="파일 이름"):
        load_example_file(path)


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ExampleError, match="없습니다"):
        load_examples("inventory", "A02", Label, root=tmp_path)


def test_every_pack_example_file_has_a_valid_header() -> None:
    paths = sorted((REPO_ROOT / DEFAULT_ROOT).glob("*/examples/A0*.yaml"))

    assert len(paths) == 18
    for path in paths:
        load_example_file(path)
