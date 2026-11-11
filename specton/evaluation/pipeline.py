"""승인된 탐색 조건을 기존 API 그래프 전체에 연결한다. 운영 API는 이 도구를 켜지 않는다."""

import hashlib
import json
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field, model_validator

from specton.agent_nodes import design_nodes, review_nodes, router_node
from specton.api.main import create_graph
from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.normalized import Normalized, NormalizeResult
from specton.design_rules_node import design_rules_node
from specton.evaluation.lexicon_overlay import (
    Identifier,
    LexiconOverlay,
    Sha256,
    Strict,
    Text,
    load_overlay,
)
from specton.graph import GraphState, Node
from specton.llm.client import LLMClient
from specton.llm.types import LLMRequest, LLMResult, Message
from specton.nodes.common import data_block, unwrap_data
from specton.normalization_node import normalization_node
from specton.review.normalization_findings import failure_mapper, rule_severities
from specton.review.rule_policy import load_policies

ACTIVE_RUN: ContextVar[str | None] = ContextVar("evaluation_run_id", default=None)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PipelineInput(Strict):
    case_id: Identifier
    path: Text
    sha256: Sha256
    approved_model: Text | None = None
    approved_model_sha256: Sha256 | None = None
    naming_guidance: dict[Text, Text] = Field(default_factory=dict)


def condition_subject(raw: dict[str, Any]) -> str:
    body = {k: v for k, v in raw.items() if k != "approval"}
    body.setdefault("domain_context", "with_pack")
    body["inputs"] = [
        PipelineInput.model_validate(item).model_dump(mode="json") for item in body["inputs"]
    ]
    return digest(body)


class PipelineApproval(Strict):
    role: Literal["R1"]
    reviewer: Text
    decision: Literal["approved"]
    subject_sha256: Sha256
    reference: Text


class PipelineSpec(Strict):
    schema_version: Literal[1]
    scope: Literal["post_observation_exploration"]
    condition_id: Identifier
    mode: Literal["fresh_generation", "approved_model_replay"]
    domain_context: Literal[
        "with_pack", "without_domain_prompt_context", "without_pack_context"
    ] = "with_pack"
    overlay: Text
    overlay_subject_sha256: Sha256
    inputs: tuple[PipelineInput, ...] = Field(min_length=1)
    approval: PipelineApproval

    @model_validator(mode="after")
    def check_subject(self) -> "PipelineSpec":
        if self.approval.subject_sha256 != condition_subject(
            self.model_dump(mode="json", exclude={"approval"})
        ):
            raise ValueError("전체 실행 조건과 R1 승인 해시가 다릅니다")
        if len({i.case_id for i in self.inputs}) != len(self.inputs) or len(
            {i.sha256 for i in self.inputs}
        ) != len(self.inputs):
            raise ValueError("전체 실행 입력이 중복됩니다")
        if self.mode == "approved_model_replay" and any(
            i.approved_model is None or i.approved_model_sha256 is None for i in self.inputs
        ):
            raise ValueError("승인 모델 재생에는 모델 파일과 해시가 필요합니다")
        if self.mode == "fresh_generation" and any(
            i.approved_model is not None or i.approved_model_sha256 is not None for i in self.inputs
        ):
            raise ValueError("새 생성 조건에는 고정 모델을 넣을 수 없습니다")
        return self


@dataclass(frozen=True)
class PipelineCondition:
    path: Path
    spec: PipelineSpec
    overlay: LexiconOverlay
    snapshot_sha256: str

    @property
    def subject(self) -> str:
        return self.spec.approval.subject_sha256

    def resolve(self, name: str) -> Path:
        path = Path(name)
        return path if path.is_absolute() else self.path.parent / path

    def assert_current(self) -> None:
        if file_hash(self.path) != self.snapshot_sha256:
            raise ValueError("전체 실행 조건 파일이 변경됐습니다")
        if (
            condition_subject(self.spec.model_dump(mode="json", exclude={"approval"}))
            != self.subject
        ):
            raise ValueError("메모리의 전체 실행 조건이 변경됐습니다")
        self.overlay.assert_current()
        if self.overlay.subject_sha256 != self.spec.overlay_subject_sha256:
            raise ValueError("선정 해시가 전체 실행 조건과 다릅니다")
        for item in self.spec.inputs:
            path = self.resolve(item.path)
            if path.is_symlink() or file_hash(path) != item.sha256:
                raise ValueError("전체 실행 입력의 해시가 다릅니다")
            if item.approved_model is not None:
                model = self.resolve(item.approved_model)
                if model.is_symlink() or file_hash(model) != item.approved_model_sha256:
                    raise ValueError("승인 모델 파일이 변경됐습니다")
                DesignState.model_validate_json(model.read_text())

    def case(self, design: DesignState) -> PipelineInput:
        matches = [
            item for item in self.spec.inputs if item.sha256 == design.versions.document_hash
        ]
        if len(matches) != 1:
            raise ValueError("현재 실행에 연결된 승인 입력이 없습니다")
        return matches[0]

    def provenance(self) -> dict[str, str]:
        return {
            "evaluation_scope": self.spec.scope,
            "evaluation_condition": self.subject,
            "condition_id": self.spec.condition_id,
            "design_source": self.spec.mode,
            "domain_context": self.spec.domain_context,
            "overlay_subject_sha256": self.overlay.subject_sha256,
            "overlay_approval_mode": self.overlay.provenance()["overlay_approval_mode"],
        }

    def wrap(self, settings: Settings, name: str, node: Node) -> Node:
        def guarded(state: GraphState) -> Mapping[str, Any]:
            self.assert_current()
            if name == "parse":
                docs = state.get("documents", ())
                if len(docs) != 1:
                    raise ValueError("평가 실행은 승인된 입력 한 개씩 처리합니다")
                root = settings.storage_dir.resolve()
                uploaded = (root / docs[0]["storage_ref"]).resolve()
                if not uploaded.is_relative_to(root):
                    raise ValueError("평가 입력이 저장 경로 밖에 있습니다")
                sha = file_hash(uploaded)
                if sha not in {i.sha256 for i in self.spec.inputs}:
                    raise ValueError("승인되지 않은 평가 입력입니다")
                update = dict(node(state))
                design = update["design"]
                update["design"] = design.evolve(versions=design.versions.evolve(document_hash=sha))
                update["evaluation_condition"] = self.subject
                update["notes"] = (
                    *update.get("notes", ()),
                    {"message": f"평가 조건: {self.spec.mode}", "payload": self.provenance()},
                )
                return update
            if state.get("evaluation_condition") != self.subject:
                raise ValueError("체크포인트의 평가 조건이 다릅니다")
            self.case(state["design"])
            return node(state)

        def contextual(state: GraphState) -> Mapping[str, Any]:
            token = ACTIVE_RUN.set(state["design"].run_id)
            try:
                return guarded(state)
            finally:
                ACTIVE_RUN.reset(token)

        return contextual

    def policy_digest(self) -> str:
        return digest({"base": self.overlay.policy_digest(), "evaluation_condition": self.subject})

    def normalize(self, design: DesignState) -> NormalizeResult:
        self.assert_current()
        self.case(design)
        result = self.overlay.normalize_result(design)
        if isinstance(result, Normalized):
            return Normalized(model=result.model.evolve(policy_digest=self.policy_digest()))
        return result

    def naming_context(self, design: DesignState) -> dict[str, Any]:
        self.assert_current()
        item = self.case(design)
        return {
            "naming_lexicon": self.overlay.lexicon,
            "naming_guidance": item.naming_guidance,
            "naming_words": [
                a.word.model_dump(mode="json", include={"word", "english", "abbreviation"})
                for a in self.overlay.spec.additions
            ],
        }

    def replay_node(self, stage: str) -> Node:
        def replay(state: GraphState) -> Mapping[str, Any]:
            design = state["design"]
            item = self.case(design)
            if item.approved_model is None:
                raise ValueError("재생할 승인 모델이 없습니다")
            seed = DesignState.model_validate_json(self.resolve(item.approved_model).read_text())
            if stage == "a01":
                # 실제 parse/HITL의 원문·결정은 보존하고, 같은 입력의 승인 요구사항만 재생한다.
                refs = {b.source_ref for b in design.source_requirements if b.analysable}
                if any(r.source_ref not in refs for r in seed.requirements):
                    raise ValueError("승인 모델의 원문 위치가 현재 입력과 다릅니다")
                update = design.evolve(requirements=seed.requirements)
            else:
                if design.requirements != seed.requirements:
                    raise ValueError("승인 모델의 요구사항을 변경한 실행은 재생할 수 없습니다")
                if stage == "a02":
                    update = design.evolve(functions=seed.functions)
                elif stage == "a03":
                    update = design.evolve(entities=seed.entities, functions=seed.functions)
                else:
                    update = design.evolve(relationships=seed.relationships)
            return {
                "design": update,
                "notes": (
                    {
                        "message": f"{stage}: R1 승인 모델 재생",
                        "payload": {
                            "design_source": "approved_model_replay",
                            "approved_model_sha256": item.approved_model_sha256,
                        },
                    },
                ),
            }

        return replay


def load_condition(path: Path) -> PipelineCondition:
    path = path.resolve()
    spec = PipelineSpec.model_validate_json(path.read_text())
    folder = Path(spec.overlay)
    if not folder.is_absolute():
        folder = path.parent / folder
    overlay = load_overlay(folder)
    result = PipelineCondition(path, spec, overlay, file_hash(path))
    result.assert_current()
    return result


class WithoutDomainContext(LLMClient):
    """few-shot·팩 용어·관측 후 명명 힌트만 제거한다. 원문·검증 정책은 동일하다."""

    def __init__(self, inner: LLMClient, *, keep_naming_guidance: bool = False) -> None:
        self.inner = inner
        self.keep_naming_guidance = keep_naming_guidance

    def complete[OutputT: BaseModel](
        self, request: LLMRequest, output_model: type[OutputT], *, token_budget: int | None = None
    ) -> LLMResult[OutputT]:
        data = json.loads(unwrap_data(request.messages[-1].content))
        data.pop("pack", None)
        if not self.keep_naming_guidance:
            data.pop("evaluation_naming", None)
        version_suffix = (
            "-without-pack-context-v1"
            if self.keep_naming_guidance
            else "-without-domain-context-v1"
        )
        clean = request.model_copy(
            update={
                "messages": (request.messages[0], Message(role="user", content=data_block(data))),
                "prompt_version": request.prompt_version + version_suffix,
            }
        )
        return self.inner.complete(clean, output_model, token_budget=token_budget)


def create_evaluation_graph(
    settings: Settings,
    checkpointer: BaseCheckpointSaver[Any],
    condition: PipelineCondition,
    *,
    client: LLMClient | None = None,
    agent_nodes: Mapping[str, Node] | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
    condition.assert_current()
    if settings.pack_root.resolve() != condition.overlay.base_root.resolve():
        raise ValueError("평가 실행은 승인된 팩 사본 경로를 사용해야 합니다")
    if client is None and agent_nodes is None:
        from specton.llm.openai_transport import openai_client

        client = openai_client(settings)
    if client is not None and condition.spec.domain_context == "without_domain_prompt_context":
        client = WithoutDomainContext(client)
    elif client is not None and condition.spec.domain_context == "without_pack_context":
        client = WithoutDomainContext(client, keep_naming_guidance=True)
    nodes: dict[str, Node]
    if agent_nodes is not None:
        nodes = dict(agent_nodes)
    else:
        assert client is not None

        def get_client() -> LLMClient:
            assert client is not None
            return client

        nodes = {
            **design_nodes(get_client, settings, naming_context=condition.naming_context),
            **review_nodes(get_client, settings),
            "a09": router_node(get_client, settings),
        }
    if condition.spec.mode == "approved_model_replay":
        nodes.update({name: condition.replay_node(name) for name in ("a01", "a02", "a03", "a04")})
    root = settings.pack_root
    mapper = failure_mapper(rule_severities(root=root), policies=load_policies(root=root))
    return create_graph(
        settings,
        checkpointer,
        agent_nodes=nodes,
        node_overrides={
            "normalize": normalization_node(mapper, root=root, normalizer=condition.normalize),
            "rules": design_rules_node(
                root=root,
                expected_policy_digest=condition.policy_digest(),
                additional_words=tuple(a.word for a in condition.overlay.spec.additions),
            ),
        },
        node_wrapper=lambda name, node: condition.wrap(settings, name, node),
    )
