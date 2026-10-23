"""저장소 문서·설정이 저장소 밖 문서에 기대지 않는지 검사한다.

외부 기획 폴더의 경로·문서명·ID(O-xx 등)가 다시 들어오면 실패한다.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_SUFFIXES = {".md", ".yaml", ".yml", ".toml", ".json", ".py"}
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
    "planning decision ids (use ADR numbers)": re.compile(
        r"\b(?:O-\d{2}|D-00\d)\b|(?<![\w.%-])[AB][1-7](?![\w.%-])"
    ),
    "WBS ids (use issue numbers)": re.compile(r"\bW\d{2}\b"),
}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    return [
        path
        for path in result.stdout.splitlines()
        if Path(path).suffix in CHECKED_SUFFIXES
        and not path.startswith(EXCLUDED_PREFIXES)
        and path != THIS_FILE
    ]


def find_violations(files: list[str]) -> list[str]:
    violations = []
    for path in files:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    violations.append(f"{path}:{line_no} [{label}] {line.strip()[:80]}")
    return violations


def test_forbidden_patterns_are_detected() -> None:
    sample = "원본: 상위 기획 폴더 `docs/개발착수_문서/02.md`, O-03"
    hits = {label for label, pattern in FORBIDDEN.items() if pattern.search(sample)}
    assert hits == {
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
    assert any(pattern.search(line) for pattern in FORBIDDEN.values())


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
    assert not any(pattern.search(line) for pattern in FORBIDDEN.values())


def test_repository_files_do_not_reference_external_documents() -> None:
    violations = find_violations(tracked_files())
    if violations:
        pytest.fail("저장소 밖 문서를 참조함:\n" + "\n".join(violations))
