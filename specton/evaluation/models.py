"""통합 채점 입력. 정답·허용 매칭은 사람이 승인한 자료를 변환해 제공한다."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Label = Literal["FR", "NFR"]


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def unique(values: list[str], where: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{where}: ID 중복")


class WarningPolicy(Record):
    """필수 경고·필수 대안 그룹·참고 경고를 서로 겹치지 않게 둔다."""

    required_warnings: frozenset[Text] = frozenset()
    required_warning_groups: tuple[frozenset[Text], ...] = ()
    allowed_warnings: frozenset[Text] = frozenset()

    @model_validator(mode="after")
    def disjoint(self) -> Self:
        if self.required_warnings & self.allowed_warnings:
            raise ValueError("필수·허용 경고는 겹치지 않아야 합니다")
        used = set(self.required_warnings | self.allowed_warnings)
        for group in self.required_warning_groups:
            if len(group) < 2 or used & group:
                raise ValueError("경고 대안 그룹은 두 종류 이상이며 다른 정책과 겹치면 안 됩니다")
            used.update(group)
        return self


class Truth(WarningPolicy):
    id: Text
    source_id: Text
    label: Label


class Prediction(Record):
    id: Text
    source_id: Text
    label: Label
    warnings: frozenset[Text] = frozenset()


class Alignment(Record):
    gold: Text
    predicted: Text


class Classification(Record):
    gold: tuple[Truth, ...] = ()
    predicted: tuple[Prediction, ...] = ()
    alignments: tuple[Alignment, ...] = ()
    source_warnings: dict[Text, WarningPolicy] = Field(default_factory=dict)
    allowed_split_counts: dict[Text, frozenset[Annotated[int, Field(gt=0)]]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def references(self) -> Self:
        unique([i.id for i in self.gold], "정답 요구사항")
        unique([i.id for i in self.predicted], "출력 요구사항")
        unique([i.gold for i in self.alignments], "정답 정렬")
        unique([i.predicted for i in self.alignments], "출력 정렬")
        gold, predicted = {i.id: i for i in self.gold}, {i.id: i for i in self.predicted}
        self.check_split_counts()
        if self.source_warnings.keys() - {i.source_id for i in self.gold}:
            raise ValueError("경고 정책이 없는 정답 원문을 가리킵니다")
        for item in self.gold:
            if item.source_id in self.source_warnings and (
                item.required_warnings or item.required_warning_groups or item.allowed_warnings
            ):
                raise ValueError("원문·분할 항목에 경고를 이중 배치할 수 없습니다")
        for match in self.alignments:
            if match.gold not in gold or match.predicted not in predicted:
                raise ValueError("분류 정렬이 없는 요구사항을 가리킵니다")
            if gold[match.gold].source_id != predicted[match.predicted].source_id:
                raise ValueError("서로 다른 원문 블록을 정렬할 수 없습니다")
        return self

    def check_split_counts(self) -> None:
        for source, counts in self.allowed_split_counts.items():
            primary = sum(item.source_id == source for item in self.gold)
            if primary == 0 or primary not in counts:
                raise ValueError("허용 분할 수에 원문 정답의 분할 수가 포함돼야 합니다")


class MatchGroup(Record):
    gold: frozenset[Text] = Field(min_length=1)
    predicted: frozenset[Text] = Field(min_length=1)


class MatchSet(Record):
    """승인된 동등 그룹 하나를 TP 하나로 센다. 분할·병합의 경계를 추측하지 않는다."""

    gold: frozenset[Text] = frozenset()
    predicted: frozenset[Text] = frozenset()
    matches: tuple[MatchGroup, ...] = ()

    @field_validator("gold", "predicted", mode="before")
    @classmethod
    def reject_duplicate_ids(cls, value: object) -> object:
        if isinstance(value, (list, tuple)) and all(isinstance(i, str) for i in value):
            unique(list(value), "매칭 대상")
        return value

    @model_validator(mode="after")
    def no_double_count(self) -> Self:
        used_gold: set[str] = set()
        used_predicted: set[str] = set()
        for match in self.matches:
            if not match.gold <= self.gold or not match.predicted <= self.predicted:
                raise ValueError("매칭이 없는 대상을 가리킵니다")
            if used_gold & match.gold or used_predicted & match.predicted:
                raise ValueError("대상을 여러 매칭 그룹에 중복 사용할 수 없습니다")
            used_gold.update(match.gold)
            used_predicted.update(match.predicted)
        return self


class Matching(MatchSet):
    """필수 대응과 허용 대응을 분리한다. 선택 객체도 분모·오탐에서 제외한다."""

    permitted: MatchSet = Field(default_factory=MatchSet)

    @model_validator(mode="after")
    def separate_permitted(self) -> Self:
        if self.gold & self.permitted.gold:
            raise ValueError("필수·허용 대상은 겹치지 않아야 합니다")
        required_hits = {p for match in self.matches for p in match.predicted}
        permitted_hits = {p for match in self.permitted.matches for p in match.predicted}
        if self.permitted.predicted != permitted_hits:
            raise ValueError("허용 대상 제외에는 승인된 대응이 필요합니다")
        if not permitted_hits <= self.predicted or permitted_hits & required_hits:
            raise ValueError("허용 대상은 실제 출력이며 필수 대응과 겹치지 않아야 합니다")
        return self


class Detection(Matching):
    """결함 ID와 지적 ID의 승인 매칭. rule/llm/filtered를 각각 입력한다."""

    normal: bool = False

    @model_validator(mode="after")
    def normal_has_no_defects(self) -> Self:
        if self.normal and self.gold:
            raise ValueError("정상 사례에는 기대 결함이 없어야 합니다")
        return self


class Versions(Record):
    commit: Text
    pack: Text
    pack_version: Text
    common_version: Text
    policy_digest: Hash
    models: dict[Text, Text] = Field(min_length=1)
    prompts: dict[Text, Text] = Field(min_length=1)


class Document(Record):
    document_id: Text
    input_hash: Hash
    run_id: Text
    condition: Text = "with_pack"
    trial: int = Field(default=1, ge=1)
    status: Literal["completed", "failed", "not_run", "cancelled", "incomplete"]
    versions: Versions
    classification: Classification = Field(default_factory=Classification)
    objects: dict[Literal["functions", "entities", "attributes", "relationships"], Matching] = (
        Field(default_factory=dict)
    )
    detections: dict[Literal["rule", "llm", "filtered"], Detection] = Field(default_factory=dict)
    ddl: Literal["passed", "failed", "error", "unverified", "not_generated"] = "not_generated"
    wall_time_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    retries: int | None = Field(default=None, ge=0)
    reworks: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_basis: Text | None = None

    @model_validator(mode="after")
    def honest_status(self) -> Self:
        if self.status != "completed" and self.ddl == "passed":
            raise ValueError("미완료 실행은 DDL 성공으로 셀 수 없습니다")
        if self.cost_usd is not None and self.cost_basis is None:
            raise ValueError("비용에는 단가 기준 날짜·출처가 필요합니다")
        if self.status == "not_run" and (self.input_tokens or self.output_tokens):
            raise ValueError("미실행에는 사용 토큰을 기록할 수 없습니다")
        return self


class Evaluation(Record):
    dataset: Text
    gold_version: Text
    gold_variant: Text
    gold_hash: Hash
    approval_ref: Text
    gold_status: Literal["approved"]
    matching_status: Literal["approved"]
    planned_document_ids: frozenset[Text] = Field(min_length=1)
    documents: tuple[Document, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_runs(self) -> Self:
        unique([d.run_id for d in self.documents], "실행")
        keys = [f"{d.document_id}\0{d.condition}\0{d.trial}" for d in self.documents]
        unique(keys, "문서·조건·반복")
        sources: dict[str, str] = {}
        populations: dict[tuple[str, int], set[str]] = {}
        versions: dict[str, Versions] = {}
        for document in self.documents:
            previous = sources.setdefault(document.document_id, document.input_hash)
            if previous != document.input_hash:
                raise ValueError("같은 문서의 조건·반복 간 입력 해시가 다릅니다")
            populations.setdefault((document.condition, document.trial), set()).add(
                document.document_id
            )
            frozen = versions.setdefault(document.condition, document.versions)
            if frozen != document.versions:
                raise ValueError("같은 조건에서 코드·팩·모델·프롬프트 버전이 다릅니다")
        if any(ids != self.planned_document_ids for ids in populations.values()):
            raise ValueError("조건·반복마다 평가 예정 문서를 모두 기록해야 합니다 (미실행 포함)")
        return self
