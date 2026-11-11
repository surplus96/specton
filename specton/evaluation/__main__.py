"""python -m specton.evaluation input.json --out report.json (네트워크 호출 없음)."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from specton.evaluation.models import Evaluation
from specton.evaluation.report import build_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="승인 정답·매칭과 저장된 실행의 오프라인 채점")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        batch = Evaluation.model_validate_json(args.input.read_text(encoding="utf-8"))
        report = build_report(batch)
        # 기존 정답·보고서는 덮어쓰지 않는다. 같은 경로·심볼릭 링크·하드 링크도 거절된다.
        with args.out.open("x", encoding="utf-8") as target:
            target.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except (OSError, ValidationError, ValueError) as exc:
        print(f"채점을 완료하지 못했습니다: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"채점 완료: {len(batch.documents)}개 실행, 조건 {len(report['conditions'])}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
