"""
Pure transformation: legacy Business Analyst Agent output (the exact
dict shape produced by Business-Analyst-Agent-main/agent/nodes.py's
write_requirements_json) -> the canonical contract defined by
ba_contract_prototype/schema.py, plus an explicit provenance mapping.

This module is read-only with respect to the legacy dict it is given:
adapt() never assigns into its `legacy` argument, only reads from it
and builds entirely new structures. See adapter/tests/test_adapter.py
for a test that proves this with a before/after deep-equality check.

"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from ba_contract_prototype import schema


class MappingError(Exception):
    """
    Raised when a legacy reference cannot be mapped to a canonical ID
    unambiguously (e.g. a user story's fr_ids entry, or an acceptance
    criterion's story_id, points at a legacy ID that was never seen in
    the corresponding legacy array). Never silently resolved to an
    arbitrary item — the caller must decide what to do with this.
    """


@dataclass
class AdapterResult:
    contract: dict
    provenance: dict


def _unresolved(reason: str) -> dict:
    return {"status": schema.UNRESOLVED_STATUS, "reason": reason}


def _tasks_or_unresolved(value) -> object:
    if isinstance(value, list):
        items = [t.strip() for t in value if isinstance(t, str) and t.strip()]
        if items:
            return items
    return _unresolved(
        "The client did not provide a task breakdown (the 'tasks' question was skipped "
        "or not asked in this run)."
    )


def _business_case_or_unresolved(value) -> object:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _unresolved(
        "The client did not provide a business case (the 'business case' question was "
        "skipped or not asked in this run)."
    )


def _adapt_functional_requirements(legacy_frs: list) -> tuple[list, dict]:
    """Returns (canonical_frs, legacy_id -> canonical_id map)."""
    id_map: dict = {}
    canonical: list = []
    for i, fr in enumerate(legacy_frs, start=1):
        legacy_id = fr.get("id") if isinstance(fr, dict) else None
        if legacy_id in id_map:
            raise MappingError(
                f"Duplicate legacy functional_requirements id {legacy_id!r} "
                f"encountered at position {i}; cannot map unambiguously."
            )
        canonical_id = f"FR-{i:03d}"
        id_map[legacy_id] = canonical_id
        canonical.append({
            "id": canonical_id,
            "text": fr.get("text") if isinstance(fr, dict) else None,
            "source_feature": fr.get("feature") if isinstance(fr, dict) else None,
        })
    return canonical, id_map


def _adapt_user_stories(legacy_stories: list, fr_id_map: dict) -> tuple[list, dict]:
    """Returns (canonical_stories, legacy_id -> canonical_id map)."""
    id_map: dict = {}
    canonical: list = []
    for i, story in enumerate(legacy_stories, start=1):
        if not isinstance(story, dict):
            raise MappingError(f"user_stories[{i - 1}] is not an object; cannot adapt.")
        legacy_id = story.get("id")
        if legacy_id in id_map:
            raise MappingError(
                f"Duplicate legacy user_stories id {legacy_id!r} "
                f"encountered at position {i}; cannot map unambiguously."
            )
        canonical_id = f"US-{i:03d}"
        id_map[legacy_id] = canonical_id

        legacy_fr_ids = story.get("fr_ids", [])
        if not isinstance(legacy_fr_ids, list):
            raise MappingError(
                f"User story {legacy_id!r} has non-list 'fr_ids' "
                f"({type(legacy_fr_ids).__name__}); cannot remap its references."
            )
        remapped_fr_ids = []
        for fid in legacy_fr_ids:
            if fid not in fr_id_map:
                raise MappingError(
                    f"User story {legacy_id!r} references unknown functional "
                    f"requirement id {fid!r}; cannot map unambiguously."
                )
            remapped_fr_ids.append(fr_id_map[fid])

        canonical.append({
            "id": canonical_id,
            "as_a": story.get("as_a"),
            "i_want": story.get("i_want"),
            "so_that": story.get("so_that"),
            "fr_ids": remapped_fr_ids,
            "priority": story.get("priority"),  # extra field, not required by the canonical
                                                  # schema but preserved rather than dropped
        })
    return canonical, id_map


def _adapt_acceptance_criteria(legacy_criteria: list, us_id_map: dict) -> tuple[list, list]:
    """
    Returns (canonical_criteria, provenance_list).

    Legacy acceptance-criterion IDs are explicitly NOT trusted to be
    globally unique (confirmed defect, Phase 3B.1: this repo's own
    sample reuses "AC-1".."AC-4" across every story). Canonical IDs are
    therefore derived purely from GLOBAL LIST POSITION, which is the
    one thing guaranteed unique regardless of what the legacy id string
    says. Provenance records, for every item: its legacy id, its legacy
    story id, its 0-based original position in the full legacy list,
    and its 1-based position within its own story — enough to uniquely
    identify the source item even though the legacy id alone cannot.
    """
    canonical: list = []
    provenance: list = []
    position_within_story: dict = {}

    for pos, crit in enumerate(legacy_criteria):
        if not isinstance(crit, dict):
            raise MappingError(f"acceptance_criteria[{pos}] is not an object; cannot adapt.")
        legacy_story_id = crit.get("story_id")
        if legacy_story_id not in us_id_map:
            raise MappingError(
                f"Acceptance criterion at position {pos} (legacy id "
                f"{crit.get('id')!r}) references unknown story id "
                f"{legacy_story_id!r}; cannot map unambiguously."
            )
        canonical_story_id = us_id_map[legacy_story_id]
        position_within_story[legacy_story_id] = position_within_story.get(legacy_story_id, 0) + 1
        canonical_id = f"AC-{pos + 1:03d}"

        canonical.append({
            "id": canonical_id,
            "story_id": canonical_story_id,
            "given": crit.get("given"),
            "when": crit.get("when"),
            "then": crit.get("then"),
        })
        provenance.append({
            "canonical_id": canonical_id,
            "legacy_id": crit.get("id"),
            "legacy_story_id": legacy_story_id,
            "canonical_story_id": canonical_story_id,
            "original_list_position": pos,
            "position_within_story": position_within_story[legacy_story_id],
        })
    return canonical, provenance


def _adapt_non_functional_requirements(legacy_nfrs: list) -> list:
    """Legacy NFRs are plain strings (confirmed, Phase 3A.2/3B.1). Each
    becomes a canonical {id, text} object with a position-based id."""
    canonical = []
    for i, text in enumerate(legacy_nfrs, start=1):
        if not isinstance(text, str):
            raise MappingError(
                f"non_functional_requirements[{i - 1}] is not a string "
                f"({type(text).__name__}); cannot adapt without fabricating content."
            )
        canonical.append({"id": f"NFR-{i:03d}", "text": text})
    return canonical


def _adapt_data_models(legacy_data_entities: list) -> list:
    """
    Legacy data_entities are flat entity-name strings with no attribute
    or relationship detail (confirmed, Phase 3A.1). The canonical
    schema requires each data_models item to have 'entity' plus an
    'attributes' list — but does NOT require attributes to be
    non-empty (confirmed by reading ba_contract_prototype/validator.py
    ::_check_data_models this phase). So each entity is mapped with an
    EMPTY attributes/relationships list rather than inventing any
    attribute, type, or relationship the legacy data never specified.
    """
    canonical = []
    for name in legacy_data_entities:
        if not isinstance(name, str):
            raise MappingError(
                f"analysis.data_entities contains a non-string entry "
                f"({type(name).__name__}); cannot adapt without fabricating content."
            )
        canonical.append({"entity": name, "attributes": [], "relationships": []})
    return canonical


def adapt(legacy: dict) -> AdapterResult:
    """
    Converts one legacy requirements.json-shaped dict into the
    canonical ba_contract_prototype contract. Pure: never mutates
    `legacy`; always returns brand-new structures. Raises MappingError
    on any reference that cannot be resolved unambiguously, rather
    than guessing.
    """
    if not isinstance(legacy, dict):
        raise MappingError(f"Legacy input must be a dict, got {type(legacy).__name__}.")

    legacy_project = legacy.get("project", {}) if isinstance(legacy.get("project"), dict) else {}
    legacy_analysis = legacy.get("analysis", {}) if isinstance(legacy.get("analysis"), dict) else {}
    legacy_scope = legacy_analysis.get("scope", {}) if isinstance(legacy_analysis.get("scope"), dict) else {}

    legacy_frs = legacy_analysis.get("functional_requirements", [])
    if not isinstance(legacy_frs, list):
        raise MappingError("analysis.functional_requirements must be a list.")
    canonical_frs, fr_id_map = _adapt_functional_requirements(legacy_frs)

    legacy_stories = legacy.get("user_stories", [])
    if not isinstance(legacy_stories, list):
        raise MappingError("user_stories must be a list.")
    canonical_stories, us_id_map = _adapt_user_stories(legacy_stories, fr_id_map)

    legacy_criteria = legacy.get("acceptance_criteria", [])
    if not isinstance(legacy_criteria, list):
        raise MappingError("acceptance_criteria must be a list.")
    canonical_criteria, ac_provenance = _adapt_acceptance_criteria(legacy_criteria, us_id_map)

    canonical_nfrs = _adapt_non_functional_requirements(legacy_analysis.get("non_functional_requirements", []))
    canonical_data_models = _adapt_data_models(legacy_analysis.get("data_entities", []))

    contract = {
        "schema_version": schema.SCHEMA_VERSION,
        "project": {
            "title": legacy_project.get("name"),
            "description": legacy_project.get("description"),
        },
        "objectives_and_goals": list(legacy_analysis.get("objectives", [])),
        # Business case and tasks: taken VERBATIM from the client's own answers
        # when the agent collected them (analysis.business_case / analysis.tasks).
        # If the client skipped the question, or the data comes from an older run
        # that never asked it, the field stays an explicit "unresolved" marker -
        # nothing is ever invented to fill it.
        "tasks": _tasks_or_unresolved(legacy_analysis.get("tasks")),
        "business_case": _business_case_or_unresolved(legacy_analysis.get("business_case")),
        "functional_requirements": canonical_frs,
        "non_functional_requirements": canonical_nfrs,
        "user_stories": canonical_stories,
        "acceptance_criteria": canonical_criteria,
        "in_scope_features": list(legacy_scope.get("in", [])),
        "data_models": canonical_data_models,


        "legacy_functional_requirements_raw": copy.deepcopy(legacy_frs),
        "legacy_project_type": legacy_project.get("type"),
        "legacy_stakeholders": copy.deepcopy(legacy_analysis.get("stakeholders", [])),
        "legacy_risks": copy.deepcopy(legacy_analysis.get("risks", [])),
        "legacy_scope_out": copy.deepcopy(legacy_scope.get("out", [])),
        "legacy_qa": copy.deepcopy(legacy.get("qa", [])),
        "legacy_ui": copy.deepcopy(legacy.get("ui", {})),
        "legacy_validation": copy.deepcopy(legacy.get("validation", {})),
    }

    provenance = {
        "fr_id_map": dict(fr_id_map),
        "us_id_map": dict(us_id_map),
        "reverse_fr_id_map": {v: k for k, v in fr_id_map.items()},
        "reverse_us_id_map": {v: k for k, v in us_id_map.items()},
        "acceptance_criteria": ac_provenance,
    }

    return AdapterResult(contract=contract, provenance=provenance)
