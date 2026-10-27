"""설정형 리뷰어 노드 (04 문서, ADR-0008).

관점 설정(Perspective)으로 프롬프트를 만들어 공통 LLM client로 호출하고,
결과를 관점별 BranchResult(공통 Finding)로 돌려준다.
- parallel: 관점마다 1회 호출. 관점을 동시에 실행하는 것은 그래프(#18)가 맡는다.
- combined: 모든 관점을 1회 호출로 검토한다.
한 관점이 실패해도 다른 관점의 결과는 남기고, 실패는 ok=False와 오류 코드로 표시한다.
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from specton.config import Settings
from specton.contracts import BranchResult, DesignState, Finding, FindingDraft, FindingSource
from specton.llm.client import LLMClient
from specton.llm.errors import LLMError
from specton.llm.types import CallRecord
from specton.nodes.common import build_request, data_block
from specton.packs.examples import FewShot, load_examples
from specton.review.perspective import InputSection, Perspective

logger = logging.getLogger(__name__)

COMBINED_STAGE = "REVIEW"
SECTION_ORDER: tuple[InputSection, ...] = ("requirements", "functions", "entities", "relationships")

# 입력 속 지시 무시·ID 생성 금지·원문 인용은 공통 규칙(specton.nodes.common)이 붙인다.
REVIEW_RULES = """\
너는 데이터 모델 설계 검토자다. 아래 관점으로 설계를 검토하고 문제만 지적한다.
- targets에는 문제가 있는 설계 요소의 id를, evidence에는 근거 요구사항 문장을 넣는다.
- severity는 major·minor만 쓴다. 요구를 어겨 고쳐야 하면 major, 개선 의견이면 minor다.
- 문제가 없으면 findings를 비운다."""

COMBINED_RULE = "- 관점마다 reviewer_id로 결과를 나누고, 모든 관점을 빠짐없이 돌려준다."


class _Output(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewOutput(_Output):
    """parallel 방식의 LLM 출력. 관점 하나의 지적.

    findings는 필수다. 기본값을 두면 형식이 틀린 응답("{}")이 "지적 없음"으로 통과한다.
    """

    findings: tuple[FindingDraft, ...]


class PerspectiveFindings(_Output):
    reviewer_id: str
    findings: tuple[FindingDraft, ...]


class CombinedReviewOutput(_Output):
    """combined 방식의 LLM 출력. 관점별로 나눈 지적."""

    perspectives: tuple[PerspectiveFindings, ...]


@dataclass(frozen=True)
class ReviewRun:
    """리뷰 실행 결과. 관점마다 BranchResult 하나와 호출 기록."""

    results: tuple[BranchResult, ...]
    calls: tuple[CallRecord, ...]

    @property
    def complete(self) -> bool:
        """모든 관점이 성공했는지. False면 불완전 검토로 표시한다 (TC-F14)."""
        return all(r.ok for r in self.results)


def run_review(
    client: LLMClient,
    perspectives: Sequence[Perspective],
    state: DesignState,
    settings: Settings,
    *,
    pack: str | None = None,
    token_budget: int | None = None,
) -> ReviewRun:
    """설정의 review_mode에 따라 리뷰를 실행한다. pack을 주면 관점별 few-shot 예시를 넣는다."""
    if settings.review_mode == "combined":
        return review_combined(
            client, perspectives, state, settings, pack=pack, token_budget=token_budget
        )
    runs = [
        review_perspective(client, p, state, settings, pack=pack, token_budget=token_budget)
        for p in perspectives
    ]
    return ReviewRun(
        results=tuple(r for run in runs for r in run.results),
        calls=tuple(c for run in runs for c in run.calls),
    )


def review_perspective(
    client: LLMClient,
    perspective: Perspective,
    state: DesignState,
    settings: Settings,
    *,
    pack: str | None = None,
    token_budget: int | None = None,
) -> ReviewRun:
    """관점 하나를 검토한다 (parallel 방식의 한 가지). 예시는 대화 쌍으로 넣는다."""
    request = build_request(
        settings,
        role="review",
        stage=perspective.reviewer_id,
        prompt_version=perspective.prompt_version,
        system=f"{REVIEW_RULES}\n\n{_perspective_block(perspective)}",
        data=_review_data(state, perspective.inputs),
        examples=_examples(pack, perspective),
    )

    try:
        result = client.complete(request, ReviewOutput, token_budget=token_budget)
    except LLMError as exc:
        return ReviewRun(
            results=(_failed(perspective.reviewer_id, state, exc.code),), calls=exc.calls
        )
    branch = _succeeded(perspective.reviewer_id, state, result.output.findings)
    return ReviewRun(results=(branch,), calls=result.calls)


def review_combined(
    client: LLMClient,
    perspectives: Sequence[Perspective],
    state: DesignState,
    settings: Settings,
    *,
    pack: str | None = None,
    token_budget: int | None = None,
) -> ReviewRun:
    """모든 관점을 1회 호출로 검토한다. 출력에 빠진 관점은 실패로 표시한다.

    예시는 관점 하나의 답이라 대화 쌍으로 넣으면 "모든 관점을 돌려준다"와 어긋난다.
    그래서 각 관점 블록 안에 입력·지적 예시로 넣는다.
    """
    ids = [p.reviewer_id for p in perspectives]
    request = build_request(
        settings,
        role="review",
        stage=COMBINED_STAGE,
        prompt_version=",".join(f"{p.reviewer_id}={p.prompt_version}" for p in perspectives),
        system="\n\n".join(
            [
                f"{REVIEW_RULES}\n{COMBINED_RULE}",
                *(_perspective_block(p, _examples(pack, p)) for p in perspectives),
            ]
        ),
        data=_review_data(state, tuple(s for p in perspectives for s in p.inputs)),
    )
    try:
        result = client.complete(request, CombinedReviewOutput, token_budget=token_budget)
    except LLMError as exc:
        return ReviewRun(results=tuple(_failed(i, state, exc.code) for i in ids), calls=exc.calls)
    by_id = _group_by_reviewer(result.output, ids)
    results = tuple(
        _succeeded(i, state, by_id[i]) if i in by_id else _failed(i, state, "LLM_OUTPUT_INVALID")
        for i in ids
    )
    return ReviewRun(results=results, calls=result.calls)


def _group_by_reviewer(
    output: CombinedReviewOutput, ids: Sequence[str]
) -> dict[str, tuple[FindingDraft, ...]]:
    grouped: dict[str, tuple[FindingDraft, ...]] = {}
    for part in output.perspectives:
        if part.reviewer_id not in ids:
            logger.warning("combined 출력에 설정에 없는 관점 %s가 있어 버린다", part.reviewer_id)
            continue
        grouped[part.reviewer_id] = (*grouped.get(part.reviewer_id, ()), *part.findings)
    return grouped


def _examples(pack: str | None, perspective: Perspective) -> tuple[FewShot[ReviewOutput], ...]:
    """팩의 관점 예시(`examples/<reviewer_id>.yaml`). pack이 없으면 예시 없이 검토한다."""
    if pack is None:
        return ()
    return load_examples(pack, perspective.reviewer_id, ReviewOutput)


def _perspective_block(
    perspective: Perspective, examples: Sequence[FewShot[ReviewOutput]] = ()
) -> str:
    lines = [
        f"## {perspective.reviewer_id} {perspective.name}",
        perspective.instructions,
        "점검 항목:",
        *(f"- {item}" for item in perspective.checklist),
        "지적하지 않는 경우:",
        *(f"- {item}" for item in perspective.false_positive_guards),
    ]
    for n, example in enumerate(examples, 1):
        lines += [
            f"예시 {n} 입력:",
            data_block(example.input),
            f"예시 {n} 지적:",
            example.output.model_dump_json(),
        ]
    return "\n".join(lines)


def _review_data(state: DesignState, sections: Sequence[InputSection]) -> dict[str, Any]:
    """선택한 입력만 담는다. 순서는 관점 설정과 무관하게 고정한다."""
    selected = [s for s in SECTION_ORDER if s in sections]
    return {s: [item.model_dump(mode="json") for item in getattr(state, s)] for s in selected}


def _succeeded(
    reviewer_id: str, state: DesignState, drafts: Sequence[FindingDraft]
) -> BranchResult:
    findings = tuple(
        _to_finding(d, reviewer_id, state.iteration, n) for n, d in enumerate(drafts, 1)
    )
    return BranchResult(branch=reviewer_id, revision=state.revision, ok=True, findings=findings)


def _failed(reviewer_id: str, state: DesignState, error_code: str) -> BranchResult:
    logger.warning("리뷰어 %s 실패: %s", reviewer_id, error_code)
    return BranchResult(
        branch=reviewer_id, revision=state.revision, ok=False, error_code=error_code
    )


def _to_finding(draft: FindingDraft, reviewer_id: str, iteration: int, number: int) -> Finding:
    return Finding.model_validate(
        {
            **draft.model_dump(),
            "id": f"{reviewer_id}-{iteration}-{number}",
            "source": FindingSource.LLM,
            "reviewer_id": reviewer_id,
            "fingerprint": _fingerprint(reviewer_id, draft),
            "iteration": iteration,
        }
    )


def _fingerprint(reviewer_id: str, draft: FindingDraft) -> str:
    """반복 지적을 알아보기 위한 지문. 관점·지적 종류·대상이 같으면 같다."""
    targets = sorted(f"{t.kind}:{t.id}" for t in draft.targets)
    key = json.dumps([reviewer_id, draft.kind, targets], ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
