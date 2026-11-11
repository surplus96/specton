"""python -m specton.evaluation.compose_lexicon: 네트워크 없이 별도 탐색 사본 준비."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from specton.evaluation.lexicon_overlay import compose_overlay
from specton.packs.build import BuildError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="운영 팩을 바꾸지 않는 A08 탐색 사전 사본 생성")
    parser.add_argument("spec", type=Path, help="출처·선정 근거를 기록한 비공개 JSON")
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="존재하지 않는 새 사본 경로")
    parser.add_argument(
        "--reviews", type=Path, help="선정 해시에 연결된 R1·R4 승인 또는 명시적 R1 한정 확정 JSON"
    )
    args = parser.parse_args(argv)
    try:
        result = compose_overlay(args.pack_root, args.spec, args.out, reviews=args.reviews)
    except (OSError, ValueError, BuildError) as exc:
        print(f"탐색 사전 준비 실패: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                **result.provenance(),
                "ready_to_run": result.reviews is not None,
                "base_pack_version": result.spec.base_pack_version,
                "base_common_version": result.spec.base_common_version,
                "added_word_count": len(result.spec.additions),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
