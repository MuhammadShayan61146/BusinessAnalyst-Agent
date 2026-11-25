"""
Deterministic validator for the canonical BA contract.

VALIDATOR-OWNED STATE :
    `validate()` is the ONLY function in this codebase authorized to
    produce a `validation.state` value for a BA contract. Any
    `validation` block present in the INPUT contract (e.g. because an
    upstream LLM call wrote one) is never read for its `state` — that
    key, if present, is never trusted, never copied, and never
    returned. The returned ValidationResult.state is always computed
    fresh from the structural checks below.

CRASH SAFETY :
    Every check below validates the TYPE of a value before iterating,
    indexing, or calling methods on it. A wrong type anywhere in the
    input (a string where a list was expected, an int where a string
    was expected, etc.) must produce a "malformed_field" gap and a
    FAILED result — never an uncaught exception. See
    tests/test_validator.py::CrashSafetyTests for the regression
    coverage proving this.

No network calls, no file I/O, no LLM calls. Pure function of its input
dict, by design, so it can be unit-tested with zero dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import schema

_MISSING = object()


@dataclass
class Gap:
    type: str          # e.g. "missing_field", "duplicate_id", "orphan", ...
    detail: str
    field_path: str = ""
    related_ids: list = field(default_factory=list)


@dataclass
class ValidationResult:
    state: str
    gaps: list  # list[Gap]
    unresolved_markers: list  # list[Gap] — documented-unresolved fields, not failures

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "unresolved_gaps": [g.__dict__ for g in self.gaps],
            "documented_unresolved": [g.__dict__ for g in self.unresolved_markers],
        }


# ---------------------------------------------------------------------------
# Generic field-shape helpers
# ---------------------------------------------------------------------------

def _check_list_or_unresolved(contract: dict, field_name: str, gaps: list, unresolved: list) -> None:
    value = contract.get(field_name, _MISSING)
    if value is _MISSING:
        gaps.append(Gap("missing_field", f"'{field_name}' is absent.", field_name))
        return
    if schema.is_unresolved_marker(value):
        unresolved.append(Gap("documented_unresolved", value["reason"], field_name))
        return
    if not isinstance(value, list):
        gaps.append(
            Gap("malformed_field", f"'{field_name}' must be a list or an unresolved marker.", field_name)
        )
        return
    if len(value) == 0:
        gaps.append(
            Gap(
                "unconfirmed_empty",
                f"'{field_name}' is an empty list but carries no unresolved marker "
                f"explaining why; the field must be either populated or explicitly "
                f"marked as unresolved.",
                field_name,
            )
        )


def _check_string_or_unresolved(contract: dict, field_name: str, gaps: list, unresolved: list) -> None:
    value = contract.get(field_name, _MISSING)
    if value is _MISSING:
        gaps.append(Gap("missing_field", f"'{field_name}' is absent.", field_name))
        return
    if schema.is_unresolved_marker(value):
        unresolved.append(Gap("documented_unresolved", value["reason"], field_name))
        return
    if not isinstance(value, str) or value.strip() == "":
        gaps.append(
            Gap("malformed_field", f"'{field_name}' must be a non-empty string or an unresolved marker.", field_name)
        )


def _require_nonempty_string_fields(item: dict, required_fields: tuple, field_name: str, item_index, gaps: list) -> None:
    """Appends an 'incomplete_item' gap for each missing/blank required string field."""
    for sub in required_fields:
        val = item.get(sub, _MISSING)
        if val is _MISSING or not isinstance(val, str) or val.strip() == "":
            gaps.append(
                Gap(
                    "incomplete_item",
                    f"Item at index {item_index} in '{field_name}' is missing a non-empty '{sub}'.",
                    field_name,
                )
            )


def _check_nfr(contract: dict, gaps: list) -> None:
    value = contract.get("non_functional_requirements", _MISSING)
    if value is _MISSING:
        gaps.append(Gap("missing_field", "'non_functional_requirements' is absent.", "non_functional_requirements"))
        return
    if not isinstance(value, list):
        gaps.append(
            Gap("malformed_field", "'non_functional_requirements' must be a list.", "non_functional_requirements")
        )
        return
    if len(value) == 0:
        confirmation = contract.get("non_functional_requirements_confirmation", _MISSING)
        if confirmation is _MISSING or not schema.is_nfr_confirmation(confirmation):
            gaps.append(
                Gap(
                    "unconfirmed_empty_nfr",
                    "'non_functional_requirements' is empty but "
                    "'non_functional_requirements_confirmation' is missing or malformed. "
                    "An empty NFR list must carry an explicit confirmation with a reason.",
                    "non_functional_requirements",
                )
            )
        return
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            gaps.append(Gap("malformed_field", f"Item at index {idx} in 'non_functional_requirements' is not an object.", "non_functional_requirements"))
            continue
        if not isinstance(item.get("id"), str) or item.get("id", "").strip() == "":
            gaps.append(Gap("incomplete_item", f"NFR at index {idx} is missing a non-empty 'id'.", "non_functional_requirements"))
        _require_nonempty_string_fields(item, schema.NFR_REQUIRED_STRING_FIELDS, "non_functional_requirements", idx, gaps)


# ---------------------------------------------------------------------------
# functional_requirements / user_stories / acceptance_criteria: shape,
# minimum-count, per-item completeness, and ID format/uniqueness.
# ---------------------------------------------------------------------------

def _check_required_array(
    contract: dict,
    field_name: str,
    required_string_fields: tuple,
    gaps: list,
) -> set:
    """
    Validates that `field_name` is a non-empty list of well-formed,
    structurally complete, uniquely-and-correctly-IDed items.

    Returns the set of valid IDs found (empty set if the field itself
    is malformed — callers must treat an empty set as "no safe IDs to
    reference", never as "field was fine").
    """
    value = contract.get(field_name, _MISSING)
    valid_ids: set = set()

    if value is _MISSING:
        gaps.append(Gap("missing_field", f"'{field_name}' is absent.", field_name))
        return valid_ids
    if not isinstance(value, list):
        gaps.append(Gap("malformed_field", f"'{field_name}' must be a list.", field_name))
        return valid_ids
    if len(value) < schema.MIN_REQUIRED_ITEMS:
        gaps.append(
            Gap(
                "empty_required_list",
                f"'{field_name}' must contain at least {schema.MIN_REQUIRED_ITEMS} item(s); found {len(value)}.",
                field_name,
            )
        )
        # Still fall through: if items exist in a shorter-than-min list
        # (not applicable when MIN_REQUIRED_ITEMS == 1 and len == 0, but
        # kept generic) we still want to validate them individually.

    seen_ids = set()
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            gaps.append(Gap("malformed_field", f"Item at index {idx} in '{field_name}' is not an object.", field_name))
            continue

        item_id = item.get("id", _MISSING)
        if item_id is _MISSING:
            gaps.append(Gap("incomplete_item", f"Item at index {idx} in '{field_name}' is missing 'id'.", field_name))
        elif not schema.is_well_formed_id(item_id, field_name):
            gaps.append(
                Gap(
                    "malformed_id",
                    f"ID '{item_id!r}' in '{field_name}' does not match the required "
                    f"'{schema.ID_PREFIXES[field_name]}-NNN' format.",
                    field_name,
                )
            )
        elif item_id in seen_ids:
            gaps.append(Gap("duplicate_id", f"Duplicate ID '{item_id}' found in '{field_name}'.", field_name, [item_id]))
        else:
            seen_ids.add(item_id)
            valid_ids.add(item_id)

        if required_string_fields:
            _require_nonempty_string_fields(item, required_string_fields, field_name, idx, gaps)

    return valid_ids


def _check_user_story_fr_links(us_items, fr_ids: set, retired_ids: set, gaps: list) -> set:
    """
    Validates each user story's 'fr_ids' field (type-checked BEFORE
    iteration — Phase 2.3 review item 6) and returns the set of FR ids
    that are linked by at least one well-formed story->FR reference.
    """
    story_linked_fr: set = set()
    if not isinstance(us_items, list):
        return story_linked_fr

    for story in us_items:
        if not isinstance(story, dict):
            continue
        story_id = story.get("id") if isinstance(story.get("id"), str) else "<unknown>"
        fr_ids_value = story.get("fr_ids", _MISSING)

        if fr_ids_value is _MISSING:
            gaps.append(Gap("incomplete_item", f"User story '{story_id}' is missing 'fr_ids'.", "user_stories"))
            continue
        if not isinstance(fr_ids_value, list):
            gaps.append(
                Gap(
                    "malformed_field",
                    f"User story '{story_id}' has 'fr_ids' of type "
                    f"{type(fr_ids_value).__name__}; it must be a list of FR id strings.",
                    "user_stories.fr_ids",
                )
            )
            continue
        if len(fr_ids_value) == 0:
            gaps.append(
                Gap("incomplete_item", f"User story '{story_id}' has an empty 'fr_ids' list; it must link at least one FR.", "user_stories.fr_ids")
            )
            continue

        for fr_id in fr_ids_value:
            if not isinstance(fr_id, str):
                gaps.append(
                    Gap("malformed_field", f"User story '{story_id}' has a non-string entry in 'fr_ids': {fr_id!r}.", "user_stories.fr_ids")
                )
                continue
            story_linked_fr.add(fr_id)
            if fr_id in retired_ids:
                gaps.append(
                    Gap("broken_reference", f"User story '{story_id}' references retired FR id '{fr_id}'.", "user_stories", [story_id, fr_id])
                )
            elif fr_id not in fr_ids:
                gaps.append(
                    Gap("broken_reference", f"User story '{story_id}' references nonexistent FR id '{fr_id}'.", "user_stories", [story_id, fr_id])
                )

    return story_linked_fr


def _check_acceptance_criteria_story_links(ac_items, us_ids: set, retired_ids: set, gaps: list) -> set:
    criteria_linked_story: set = set()
    if not isinstance(ac_items, list):
        return criteria_linked_story

    for crit in ac_items:
        if not isinstance(crit, dict):
            continue
        crit_id = crit.get("id") if isinstance(crit.get("id"), str) else "<unknown>"
        story_id = crit.get("story_id", _MISSING)

        if story_id is _MISSING:
            gaps.append(Gap("incomplete_item", f"Acceptance criterion '{crit_id}' is missing 'story_id'.", "acceptance_criteria"))
            continue
        if not isinstance(story_id, str):
            gaps.append(
                Gap(
                    "malformed_field",
                    f"Acceptance criterion '{crit_id}' has 'story_id' of type "
                    f"{type(story_id).__name__}; it must be a string.",
                    "acceptance_criteria.story_id",
                )
            )
            continue

        criteria_linked_story.add(story_id)
        if story_id in retired_ids:
            gaps.append(
                Gap("broken_reference", f"Acceptance criterion '{crit_id}' references retired story id '{story_id}'.", "acceptance_criteria", [crit_id, story_id])
            )
        elif story_id not in us_ids:
            gaps.append(
                Gap("broken_reference", f"Acceptance criterion '{crit_id}' references nonexistent story id '{story_id}'.", "acceptance_criteria", [crit_id, story_id])
            )

    return criteria_linked_story


def _check_retired_ids(contract: dict, gaps: list) -> set:
    """
    Validates 'retired_ids' (Phase 2.3 review items 4 & 7). Returns a
    safe set of valid retired IDs to use for the rest of validation —
    EMPTY if the field itself is malformed, so a bad 'retired_ids'
    value degrades to "nothing is treated as retired" rather than
    crashing or silently coercing (e.g. iterating the characters of a
    string, which is the exact bug being fixed here).
    """
    value = contract.get("retired_ids", [])
    if not isinstance(value, list):
        gaps.append(
            Gap("malformed_field", f"'retired_ids' must be a list of ID strings; got {type(value).__name__}.", "retired_ids")
        )
        return set()

    valid: set = set()
    seen: set = set()
    for item in value:
        if not schema.is_well_formed_any_id(item):
            gaps.append(Gap("malformed_id", f"'{item!r}' in 'retired_ids' is not a valid FR-NNN/US-NNN/AC-NNN id.", "retired_ids"))
            continue
        if item in seen:
            gaps.append(Gap("duplicate_id", f"Duplicate ID '{item}' found in 'retired_ids'.", "retired_ids", [item]))
            continue
        seen.add(item)
        valid.add(item)
    return valid


def _check_data_models(contract: dict, gaps: list, unresolved: list) -> None:
    value = contract.get("data_models", _MISSING)
    if value is _MISSING:
        gaps.append(Gap("missing_field", "'data_models' is absent.", "data_models"))
        return
    if schema.is_unresolved_marker(value):
        unresolved.append(Gap("documented_unresolved", value["reason"], "data_models"))
        return
    if not isinstance(value, list):
        gaps.append(Gap("malformed_field", "'data_models' must be a list or an unresolved marker.", "data_models"))
        return
    if len(value) == 0:
        gaps.append(
            Gap("unconfirmed_empty", "'data_models' is an empty list with no unresolved marker explaining why.", "data_models")
        )
        return

    for idx, entity in enumerate(value):
        if not isinstance(entity, dict):
            gaps.append(Gap("malformed_field", f"data_models[{idx}] is not an object.", "data_models"))
            continue
        _require_nonempty_string_fields(entity, schema.DATA_ENTITY_REQUIRED_STRING_FIELDS, "data_models", idx, gaps)

        attributes = entity.get("attributes", _MISSING)
        if attributes is _MISSING:
            gaps.append(Gap("incomplete_item", f"data_models[{idx}] is missing 'attributes'.", "data_models"))
        elif not isinstance(attributes, list):
            gaps.append(Gap("malformed_field", f"data_models[{idx}].attributes must be a list.", "data_models"))
        else:
            for a_idx, attr in enumerate(attributes):
                if not isinstance(attr, dict):
                    gaps.append(Gap("malformed_field", f"data_models[{idx}].attributes[{a_idx}] is not an object.", "data_models"))
                    continue
                _require_nonempty_string_fields(attr, schema.DATA_ATTRIBUTE_REQUIRED_STRING_FIELDS, "data_models", f"{idx}.attributes.{a_idx}", gaps)

        relationships = entity.get("relationships", [])
        if not isinstance(relationships, list):
            gaps.append(Gap("malformed_field", f"data_models[{idx}].relationships must be a list.", "data_models"))
        else:
            for r_idx, rel in enumerate(relationships):
                if not isinstance(rel, dict):
                    gaps.append(Gap("malformed_field", f"data_models[{idx}].relationships[{r_idx}] is not an object.", "data_models"))
                    continue
                _require_nonempty_string_fields(rel, schema.DATA_RELATIONSHIP_REQUIRED_STRING_FIELDS, "data_models", f"{idx}.relationships.{r_idx}", gaps)


def _check_flagged_concerns(contract: dict, gaps: list) -> bool:
    """Returns True if there is at least one UNRESOLVED flagged concern."""
    concerns = contract.get(schema.HUMAN_FLAGGED_CONCERNS_FIELD, [])
    if not isinstance(concerns, list):
        gaps.append(Gap("malformed_field", f"'{schema.HUMAN_FLAGGED_CONCERNS_FIELD}' must be a list.", schema.HUMAN_FLAGGED_CONCERNS_FIELD))
        return False
    has_open = False
    for idx, concern in enumerate(concerns):
        if not schema.is_valid_concern(concern):
            gaps.append(Gap("malformed_field", f"{schema.HUMAN_FLAGGED_CONCERNS_FIELD}[{idx}] is malformed.", schema.HUMAN_FLAGGED_CONCERNS_FIELD))
            continue
        if not concern.get("resolved", False):
            has_open = True
    return has_open


def validate(contract: dict) -> ValidationResult:
    """
    Deterministic, LLM-free validation of a BA contract.

    Returns a ValidationResult whose `.state` is one of
    schema.NOT_YET_VALIDATED / FAILED / PASSED / REQUIRES_HUMAN_REVIEW,
    computed solely from the structural checks below. Never raises on
    malformed input — every branch below type-checks before using a
    value, by design (see CRASH SAFETY note at the top of this file).
    """
    gaps: list = []
    unresolved: list = []

    if not isinstance(contract, dict):
        return ValidationResult(
            schema.FAILED,
            [Gap("malformed_field", "Contract root must be a JSON object.", "$")],
            [],
        )

    version = contract.get("schema_version")
    if version != schema.SCHEMA_VERSION:
        gaps.append(
            Gap(
                "unsupported_schema_version",
                f"Contract schema_version '{version}' is not supported (expected '{schema.SCHEMA_VERSION}').",
                "schema_version",
            )
        )
        return ValidationResult(schema.FAILED, gaps, unresolved)

    project = contract.get("project", _MISSING)
    if not isinstance(project, dict):
        gaps.append(Gap("missing_field", "'project' object is absent or malformed.", "project"))
    else:
        for sub in ("title", "description"):
            val = project.get(sub, _MISSING)
            if val is _MISSING:
                gaps.append(Gap("missing_field", f"'project.{sub}' is absent.", f"project.{sub}"))
            elif schema.is_unresolved_marker(val):
                unresolved.append(Gap("documented_unresolved", val["reason"], f"project.{sub}"))
            elif not isinstance(val, str) or val.strip() == "":
                gaps.append(Gap("malformed_field", f"'project.{sub}' must be a non-empty string.", f"project.{sub}"))

    for f in schema.LIST_OR_UNRESOLVED_FIELDS:
        if f == "data_models":
            continue
        _check_list_or_unresolved(contract, f, gaps, unresolved)

    for f in schema.STRING_OR_UNRESOLVED_FIELDS:
        _check_string_or_unresolved(contract, f, gaps, unresolved)

    _check_nfr(contract, gaps)
    _check_data_models(contract, gaps, unresolved)

    # Core deliverable arrays: non-empty, well-formed IDs, complete items.
    fr_ids = _check_required_array(contract, "functional_requirements", schema.FR_REQUIRED_STRING_FIELDS, gaps)
    us_ids = _check_required_array(contract, "user_stories", schema.US_REQUIRED_STRING_FIELDS, gaps)
    _check_required_array(contract, "acceptance_criteria", schema.AC_REQUIRED_STRING_FIELDS, gaps)

    retired_ids = _check_retired_ids(contract, gaps)

    us_items = contract.get("user_stories")
    ac_items = contract.get("acceptance_criteria")

    story_linked_fr = _check_user_story_fr_links(us_items, fr_ids, retired_ids, gaps)
    criteria_linked_story = _check_acceptance_criteria_story_links(ac_items, us_ids, retired_ids, gaps)

    for fr_id in fr_ids:
        if fr_id not in story_linked_fr:
            gaps.append(Gap("orphan", f"Functional requirement '{fr_id}' has no linked user story.", "functional_requirements", [fr_id]))
    for us_id in us_ids:
        if us_id not in criteria_linked_story:
            gaps.append(Gap("orphan", f"User story '{us_id}' has no linked acceptance criterion.", "user_stories", [us_id]))

    has_open_concern = _check_flagged_concerns(contract, gaps)

    if gaps:
        state = schema.FAILED
    elif has_open_concern or unresolved:
        state = schema.REQUIRES_HUMAN_REVIEW
    else:
        state = schema.PASSED

    return ValidationResult(state, gaps, unresolved)
