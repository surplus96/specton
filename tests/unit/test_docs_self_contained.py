"""저장소 문서·설정이 저장소 밖 문서에 기대지 않는지 검사한다.

외부 기획 폴더의 경로·문서명·ID(O-xx 등)가 다시 들어오면 실패한다.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_SUFFIXES = {".md", ".yaml", ".yml", ".toml", ".json", ".py"}
CHECKED_NAMES = {"CODEOWNERS"}
EXCLUDED_PREFIXES = ("domain_packs/sources/", "frontend/package-lock.json")
THIS_FILE = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

FORBIDDEN = {
    "external planning folder": re.compile(r"상위 기획|기획 폴더|상위 `docs/`"),
    "kickoff document names": re.compile(
        r"착수 문서|개발착수_문서|회의준비|관리표|ADR_초안|LLM_기능_설계|역할_설명서"
        r"|(?:테스트_케이스|프로젝트_RTM|요구사항_목록|개발_백로그)\.csv"
    ),
    "planning workbook": re.compile(r"기획서"),
    "external sample folder": re.compile(r"예시자료|openmaint requirement", re.IGNORECASE),
    "planning decision ids (use ADR numbers)": re.compile(r"\b(?:O-\d{2}|D-00\d)\b"),
    "WBS ids (use issue numbers)": re.compile(r"\bW\d{2}\b"),
}

# 회의 안건 번호(A1~A7, B1~B6)는 문서·설정에만 나타난다. 코드의 엑셀 셀 주소(B2 등)와
# 구분할 수 없으므로 문서·설정 파일에만 적용한다. 앞뒤 경계는 영문·숫자 기준이다
# (\w는 한글도 글자로 봐서 "B1에서"를 놓친다).
AGENDA_LABEL = "meeting agenda ids (use ADR numbers)"
AGENDA_IDS = re.compile(r"(?<![A-Za-z0-9_.%-])[AB][1-7](?![A-Za-z0-9_.%-])")
AGENDA_CHECKED_SUFFIXES = {".md", ".yaml", ".yml"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    return [
        path
        for path in result.stdout.splitlines()
        if (Path(path).suffix in CHECKED_SUFFIXES or Path(path).name in CHECKED_NAMES)
        and not path.startswith(EXCLUDED_PREFIXES)
        and path != THIS_FILE
    ]


def checks_agenda_ids(path: str) -> bool:
    return Path(path).suffix in AGENDA_CHECKED_SUFFIXES or Path(path).name in CHECKED_NAMES


def line_violations(path: str, line: str) -> list[str]:
    """한 줄에서 찾은 위반 종류. 안건 번호는 문서·설정 파일에서만 본다."""
    labels = [label for label, pattern in FORBIDDEN.items() if pattern.search(line)]
    if checks_agenda_ids(path) and AGENDA_IDS.search(line):
        labels.append(AGENDA_LABEL)
    return labels


def find_violations(files: list[str]) -> list[str]:
    violations: list[str] = []
    for path in files:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            violations.extend(
                f"{path}:{line_no} [{label}] {line.strip()[:80]}"
                for label in line_violations(path, line)
            )
    return violations


DOC = "docs/example.md"
CODE = "tests/unit/example.py"


def test_forbidden_patterns_are_detected() -> None:
    sample = "원본: 상위 기획 폴더 `docs/개발착수_문서/02.md`, O-03"
    assert set(line_violations(DOC, sample)) == {
        "external planning folder",
        "kickoff document names",
        "planning decision ids (use ADR numbers)",
    }


@pytest.mark.parametrize(
    "line",
    [
        "기준은 `테스트_케이스.csv`에 있다",
        "source: openmaint requirement A02",
        "최종 기획서 기준",
        "입력은 예시자료/openmaint에서 가져온다",
        "데이터 계약(B1 동결 후)과 같은 모양",
        "선행: W02 (#4)",
    ],
)
def test_other_external_references_are_detected(line: str) -> None:
    assert line_violations(DOC, line)


@pytest.mark.parametrize(
    "line",
    [
        "FastAPI가 생성하는 `/openapi.json`과 대조한다",
        "multipart `file`(.xlsx/.csv/.pdf)",
        "심각도 정책 (ADR-0010)",
        "openMAINT 제품 문서",
        "A01 요구사항 분석 (TC-A01)",
        "https://img.shields.io/badge/lang-%ED%95%9C%EA%B5%AD%EC%96%B4-1f6feb",
    ],
)
def test_in_repository_wording_is_allowed(line: str) -> None:
    assert not line_violations(DOC, line)


@pytest.mark.parametrize("path", [DOC, "domain_packs/common/naming.yaml", ".github/CODEOWNERS"])
def test_meeting_agenda_ids_are_detected_in_docs_and_config(path: str) -> None:
    assert line_violations(path, "타입 프로필은 B1에서 확정") == [AGENDA_LABEL]


def test_excel_cell_address_in_code_is_allowed() -> None:
    line = 'SourceRef(kind="hwpx", section=0, paragraph=4, table=1, cell="B2")'

    assert not line_violations(CODE, line)


def test_repository_files_do_not_reference_external_documents() -> None:
    violations = find_violations(tracked_files())
    if violations:
        pytest.fail("저장소 밖 문서를 참조함:\n" + "\n".join(violations))
