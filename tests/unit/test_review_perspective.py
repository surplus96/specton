from pathlib import Path

import pytest

from specton.review.perspective import (
    PERSPECTIVES_DIR,
    PerspectiveError,
    load_perspective,
    load_perspectives,
)

VALID = """\
reviewer_id: A06
name: 데이터 누락 검토
prompt_version: a06-v1
instructions: 요구 충족에 필요한 정보가 빠졌는지 본다.
checklist: [요구사항마다 저장 대상이 있는가]
inputs: [requirements, entities]
false_positive_guards: [다른 테이블에서 충족하면 지적하지 않는다]
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_every_perspective_in_reviewer_order(tmp_path: Path) -> None:
    write(tmp_path, "A06.yaml", VALID)
    write(tmp_path, "A05.yaml", VALID.replace("A06", "A05"))

    perspectives = load_perspectives(tmp_path)

    assert [p.reviewer_id for p in perspectives] == ["A05", "A06"]
    assert perspectives[1].inputs == ("requirements", "entities")


def test_bundled_example_is_valid() -> None:
    assert "A05" in [p.reviewer_id for p in load_perspectives(PERSPECTIVES_DIR)]


@pytest.mark.parametrize(
    "text",
    [
        VALID + "temperature: 0.2\n",
        VALID.replace("inputs: [requirements, entities]", "inputs: [documents]"),
        VALID.replace("checklist: [요구사항마다 저장 대상이 있는가]", "checklist: []"),
    ],
)
def test_invalid_settings_are_rejected(tmp_path: Path, text: str) -> None:
    path = write(tmp_path, "A06.yaml", text)

    with pytest.raises(PerspectiveError, match=r"A06\.yaml"):
        load_perspective(path)


def test_file_name_must_match_reviewer_id(tmp_path: Path) -> None:
    path = write(tmp_path, "A07.yaml", VALID)

    with pytest.raises(PerspectiveError, match="파일 이름"):
        load_perspective(path)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PerspectiveError, match="없습니다"):
        load_perspectives(tmp_path)
