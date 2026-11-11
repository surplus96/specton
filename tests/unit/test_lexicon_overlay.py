"""별도 탐색 사본의 출처·불변성·승인·실제 정리 경계. 모든 낱말과 승인은 합성이다."""

import hashlib
import json
import shutil
import unicodedata
from dataclasses import replace
from pathlib import Path

import pytest

from specton.config import Settings
from specton.evaluation.compose_lexicon import main as compose_main
from specton.evaluation.lexicon_overlay import compose_overlay, load_overlay
from specton.llm.stub import reply, stub_client
from specton.packs.build import BuildError
from specton.packs.provenance import policy_digest
from specton.review import eval_fixtures
from specton.review.eval_fixtures import (
    FixtureError,
    FixtureSet,
    build_report,
    case_state,
    run_cases,
)
from specton.review.eval_normalization import prepare_normalized
from specton.review.perspective import load_perspectives

ROOT = Path(__file__).parents[2] / "domain_packs"
WORD = "쩨큐가상어"
A08 = next(p for p in load_perspectives() if p.reviewer_id == "A08")


@pytest.fixture
def spec_path(tmp_path: Path) -> Path:
    source = tmp_path / "input.csv"
    source.write_text(f"word,english,abbr\n{WORD},Synthetic Lexicon Token,ZZQ\n", encoding="utf-8")
    spec = {
        "schema_version": 1,
        "scope": "evaluation_exploration",
        "condition_id": "synthetic-overlay-v1",
        "dictionary_version": "synthetic-v1",
        "pack": "inventory",
        "base_pack_version": "0.1.23",
        "base_common_version": "0.1.7",
        "base_policy_digest": policy_digest(ROOT, "inventory"),
        "sources": {
            "synthetic": {
                "path": "input.csv",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "hash_mode": "raw_bytes",
                "edition": "test-only-v1",
                "publisher": "unit test",
                "url": "https://example.invalid/lexicon.csv",
                "license": "이용허락범위 제한 없음",
                "retrieved_on": "2026-11-11",
                "encoding": "utf-8-sig",
                "word_column": "word",
                "english_column": "english",
                "abbreviation_column": "abbr",
            }
        },
        "additions": [
            {
                "word": {
                    "word": WORD,
                    "abbreviation": "ZZQ",
                    "english": "Synthetic Lexicon Token",
                    "definition": "실제 평가가 아닌 합성 도구 시험용",
                    "is_classifier": False,
                },
                "source": "synthetic",
                "row": 2,
                "selection_reason": "단위 시험 전용",
                "definition_basis": "합성 단위 시험에서 작성",
            }
        ],
    }
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


def _review_file(spec_path: Path, subject: str, roles: tuple[str, ...] = ("R1", "R4")) -> Path:
    path = spec_path.parent / "synthetic-reviews.json"
    path.write_text(
        json.dumps(
            {
                "subject_sha256": subject,
                "reviews": [
                    {
                        "role": r,
                        "reviewer": f"synthetic-{r}",
                        "decision": "approved",
                        "reference": f"unit-test-only:{r}",
                    }
                    for r in roles
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _approved(spec_path: Path) -> Path:
    draft = compose_overlay(ROOT, spec_path, spec_path.parent / "draft")
    reviews = _review_file(spec_path, draft.subject_sha256)
    approved = compose_overlay(ROOT, spec_path, spec_path.parent / "approved", reviews=reviews)
    return approved.folder


def _fixture(*, invalid_second: bool = False) -> FixtureSet:
    case = {
        "case_id": "normal-1",
        "source_id": "synthetic",
        "case": "normal",
        "requirements": [{"id": "REQ-01", "type": "FR", "text": f"{WORD} 코드를 저장한다."}],
        "entities": [
            {
                "id": "ENT-01",
                "name": WORD,
                "req_ids": ["REQ-01"],
                "attributes": [
                    {
                        "id": "ATTR-01",
                        "name": f"{WORD}코드",
                        "data_type": "varchar",
                        "length": 10,
                        "is_key": True,
                        "nullable": False,
                        "req_ids": ["REQ-01"],
                    }
                ],
            }
        ],
    }
    cases = [case]
    if invalid_second:
        other = json.loads(json.dumps(case))
        other["case_id"] = "invalid-2"
        other["entities"][0]["name"] = "쨔쨔쨔미등록"
        cases.append(other)
    return FixtureSet.model_validate(
        {"reviewer_id": "A08", "set": "synthetic", "pack": "inventory", "cases": cases}
    )


def test_draft_is_separate_and_cannot_run_without_both_reviews(spec_path: Path) -> None:
    before = policy_digest(ROOT, "inventory")
    result = compose_overlay(ROOT, spec_path, spec_path.parent / "draft")
    assert result.reviews is None
    assert policy_digest(ROOT, "inventory") == before
    assert policy_digest(result.base_root, "inventory") == before
    assert (result.base_root / "inventory/words.yaml").read_bytes() == (
        ROOT / "inventory/words.yaml"
    ).read_bytes()
    with pytest.raises(ValueError, match="R1·R4"):
        load_overlay(result.folder)
    fixture = _fixture()
    with pytest.raises(ValueError, match="승인되지 않은"):
        result.normalize(case_state(fixture, fixture.cases[0]))


def test_approved_overlay_normalizes_only_the_explicit_condition(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    fixture = _fixture()
    state = case_state(fixture, fixture.cases[0])
    with pytest.raises(ValueError, match="unresolved_name"):
        prepare_normalized(state, root=ROOT)
    result = overlay.normalize(state)
    assert result.normalized is not None
    assert result.normalized.tables[0].physical_name == "zzq"
    assert result.normalized.pack_version == "0.1.23"
    assert result.normalized.policy_digest != overlay.spec.base_policy_digest
    assert result.normalized.lexicon_digest == overlay.lexicon.digest
    assert state.normalized is None


def test_runner_uses_snapshot_and_records_exploration_provenance(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    client, transport = stub_client(reply('{"findings": []}'))
    fixture = _fixture()
    results = run_cases(client, A08, fixture, Settings(_env_file=None), overlay=overlay)
    assert len(transport.sent) == 1 and results[0].ok
    assert results[0].provenance["evaluation_scope"] == "exploration"
    assert results[0].provenance["overlay_subject_sha256"] == overlay.subject_sha256
    report = build_report(fixture, A08, results)
    assert report["evaluation_scope"] == "exploration"
    assert "unit-test-only:R4" in results[0].provenance["overlay_review_refs"]


def test_all_cases_are_preflighted_before_the_first_call(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    client, transport = stub_client()
    with pytest.raises(FixtureError, match="invalid-2"):
        run_cases(
            client, A08, _fixture(invalid_second=True), Settings(_env_file=None), overlay=overlay
        )
    assert not transport.sent


@pytest.mark.parametrize("roles", [("R1",), ("R1", "R1"), ("R4",)])
def test_partial_or_duplicate_role_approval_cannot_create_ready_copy(
    spec_path: Path, roles: tuple[str, ...]
) -> None:
    draft = compose_overlay(ROOT, spec_path, spec_path.parent / "draft")
    reviews = _review_file(spec_path, draft.subject_sha256, roles)
    out = spec_path.parent / "bad-approved"
    with pytest.raises(ValueError, match="R1·R4"):
        compose_overlay(ROOT, spec_path, out, reviews=reviews)
    assert not out.exists()


def test_review_cannot_be_reused_for_different_selection(spec_path: Path) -> None:
    draft = compose_overlay(ROOT, spec_path, spec_path.parent / "draft")
    reviews = _review_file(spec_path, draft.subject_sha256)
    spec = json.loads(spec_path.read_text())
    spec["additions"][0]["selection_reason"] = "변경된 선정 근거"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False))
    with pytest.raises(ValueError, match="해시"):
        compose_overlay(ROOT, spec_path, spec_path.parent / "changed", reviews=reviews)


@pytest.mark.parametrize("target", ["source", "base", "selection"])
def test_changed_bytes_or_metadata_invalidate_the_snapshot(spec_path: Path, target: str) -> None:
    folder = _approved(spec_path)
    if target == "source":
        path = folder / "sources/synthetic.csv"
        path.write_bytes(path.read_bytes() + b"\n")
    elif target == "base":
        path = folder / "base/common/naming.yaml"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
    else:
        path = folder / "overlay.json"
        data = json.loads(path.read_text())
        data["spec"]["dictionary_version"] = "tampered"
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_overlay(folder)


def test_existing_outputs_and_the_operating_root_cannot_be_overwritten(spec_path: Path) -> None:
    existing = spec_path.parent / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(ValueError, match="새 경로"):
        compose_overlay(ROOT, spec_path, existing)
    with pytest.raises(ValueError, match="새 경로"):
        compose_overlay(ROOT, spec_path, ROOT / "forbidden-overlay")
    assert sentinel.read_text() == "keep"


def test_nfc_duplicate_additions_are_not_silently_overwritten(spec_path: Path) -> None:
    data = json.loads(spec_path.read_text())
    duplicate = json.loads(json.dumps(data["additions"][0]))
    duplicate["word"]["word"] = unicodedata.normalize("NFD", WORD)
    data["additions"].append(duplicate)
    spec_path.write_text(json.dumps(data, ensure_ascii=False))
    with pytest.raises(ValueError, match="중복"):
        compose_overlay(ROOT, spec_path, spec_path.parent / "duplicate")


def test_cli_reports_pending_review_without_claiming_approval(
    spec_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = compose_main(
        [str(spec_path), "--pack-root", str(ROOT), "--out", str(spec_path.parent / "cli")]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["ready_to_run"] is False
    assert result["overlay_review_refs"] == "{}"
    assert WORD not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("change", ["path", "sha256", "row", "word", "aliases", "abbreviation"])
def test_invalid_source_or_word_policy_fails_before_creating_a_copy(
    spec_path: Path, change: str
) -> None:
    spec = json.loads(spec_path.read_text())
    addition = spec["additions"][0]
    if change == "path":
        spec["sources"]["synthetic"]["path"] = "../outside.csv"
    elif change == "sha256":
        spec["sources"]["synthetic"]["sha256"] = "0" * 64
    elif change == "row":
        addition["row"] = 300
    elif change == "word":
        addition["word"]["english"] = "Unsupported translation"
    elif change == "aliases":
        addition["word"]["synonyms"] = ["free alias"]
    else:
        addition["word"]["abbreviation"] = "1INVALID"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False))
    out = spec_path.parent / "invalid"
    with pytest.raises((ValueError, BuildError)):
        compose_overlay(ROOT, spec_path, out)
    assert not out.exists()


def test_default_and_exploration_cannot_be_summed_in_one_report(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    client, _ = stub_client(reply('{"findings": []}'))
    fixtures = _fixture()
    (exploration,) = run_cases(client, A08, fixtures, Settings(_env_file=None), overlay=overlay)
    fixed = replace(exploration, provenance={"evaluation_scope": "fixed"})
    with pytest.raises(FixtureError, match="합산"):
        build_report(fixtures, A08, [fixed, exploration])


def test_dictionary_is_rechecked_if_changed_after_loading(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    source = overlay.folder / "sources/synthetic.csv"
    source.write_bytes(source.read_bytes() + b"\n")
    client, transport = stub_client()
    with pytest.raises(FixtureError):
        run_cases(client, A08, _fixture(), Settings(_env_file=None), overlay=overlay)
    assert not transport.sent


def test_exploration_is_rejected_for_other_perspectives(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    perspective = next(p for p in load_perspectives() if p.reviewer_id == "A05")
    fixture = _fixture().evolve(reviewer_id="A05")
    client, transport = stub_client()
    with pytest.raises(FixtureError, match="A08"):
        run_cases(client, perspective, fixture, Settings(_env_file=None), overlay=overlay)
    assert not transport.sent


def test_exhausted_budget_retains_the_exploration_condition(spec_path: Path) -> None:
    overlay = load_overlay(_approved(spec_path))
    fixtures = _fixture()
    second = fixtures.cases[0].evolve(case_id="normal-2")
    fixtures = fixtures.evolve(cases=(*fixtures.cases, second))
    client, transport = stub_client(reply('{"findings": []}', input_tokens=10, output_tokens=10))
    results = run_cases(
        client, A08, fixtures, Settings(_env_file=None, max_tokens_per_run=20), overlay=overlay
    )
    assert len(transport.sent) == 1
    assert results[1].error_code == "BUDGET_EXCEEDED"
    assert results[1].provenance["overlay_subject_sha256"] == overlay.subject_sha256


def test_runner_cli_rejects_unapproved_dictionary_before_constructing_client(
    spec_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    draft = compose_overlay(ROOT, spec_path, spec_path.parent / "draft")
    fixtures = spec_path.parent / "cases.yaml"
    fixtures.write_text(yaml.safe_dump(_fixture().model_dump(mode="json"), allow_unicode=True))

    def forbidden_client(settings: Settings) -> None:
        pytest.fail("승인되지 않은 사전으로 client를 만들면 안 됩니다")

    monkeypatch.setattr(eval_fixtures, "openai_client", forbidden_client)
    assert (
        eval_fixtures.main(
            [str(fixtures), "--lexicon-overlay", str(draft.folder)],
            settings=Settings(_env_file=None),
        )
        == 2
    )


def test_existing_report_is_rejected_before_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "keep.json"
    output.write_text("original")

    def forbidden_client(settings: Settings) -> None:
        pytest.fail("기존 결과를 덮어쓰는 호출을 시작하면 안 됩니다")

    monkeypatch.setattr(eval_fixtures, "openai_client", forbidden_client)
    assert (
        eval_fixtures.main(
            [str(Path(__file__).parent / "data/review_eval_sample.yaml"), "--out", str(output)],
            settings=Settings(_env_file=None),
        )
        == 2
    )
    assert output.read_text() == "original"


def test_snapshot_cannot_be_replaced_with_a_link_to_the_operating_pack(spec_path: Path) -> None:
    folder = _approved(spec_path)
    shutil.rmtree(folder / "base")
    (folder / "base").symlink_to(ROOT, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        load_overlay(folder)


def test_in_memory_dictionary_change_is_not_covered_by_the_original_approval(
    spec_path: Path,
) -> None:
    overlay = load_overlay(_approved(spec_path))
    changed = replace(overlay.lexicon, tokens={**overlay.lexicon.tokens, "무검토사전어": "ZZNEW"})
    forged = replace(overlay, lexicon=changed)
    fixture = _fixture()
    with pytest.raises(ValueError, match="로드 후"):
        forged.normalize(case_state(fixture, fixture.cases[0]))
