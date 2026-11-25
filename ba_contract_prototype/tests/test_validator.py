"""
Unit tests for ba_contract_prototype.validator.

No LLM calls, no API key, no network, no file I/O beyond importing this
package. Run with:

    python3 -m unittest discover -s ba_contract_prototype/tests -v


"""

import copy
import unittest

from ba_contract_prototype import schema
from ba_contract_prototype.validator import validate


def _base_valid_contract():
    """A minimal, fully resolved, structurally valid contract."""
    return {
        "schema_version": "1.0",
        "project": {"title": "Demo Project", "description": "A demo system."},
        "objectives_and_goals": ["Let users track tasks."],
        "tasks": ["Elicit requirements", "Design schema"],
        "business_case": "Reduces manual tracking effort for the client's team.",
        "functional_requirements": [
            {"id": "FR-001", "text": "User can log in.", "source_feature": "login"}
        ],
        "non_functional_requirements": [
            {"id": "NFR-001", "text": "Login must complete within 2 seconds."}
        ],
        "user_stories": [
            {
                "id": "US-001",
                "fr_ids": ["FR-001"],
                "as_a": "user",
                "i_want": "to log in",
                "so_that": "I can access my account",
            }
        ],
        "acceptance_criteria": [
            {
                "id": "AC-001",
                "story_id": "US-001",
                "given": "valid credentials",
                "when": "I submit the login form",
                "then": "I am logged in",
            }
        ],
        "in_scope_features": ["login"],
        "data_models": [
            {
                "entity": "User",
                "attributes": [{"name": "email", "type": "string", "required": True}],
                "relationships": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Original Stage 1/2 tests (preserved; still expected to pass under the
# Phase 2.3-hardened validator)
# ---------------------------------------------------------------------------

class ValidContractTests(unittest.TestCase):
    def test_fully_resolved_contract_passes(self):
        result = validate(_base_valid_contract())
        self.assertEqual(result.state, schema.PASSED)
        self.assertEqual(result.gaps, [])
        self.assertEqual(result.unresolved_markers, [])

    def test_documented_unresolved_fields_yield_requires_human_review_not_passed(self):
        contract = _base_valid_contract()
        contract["business_case"] = {
            "status": "unresolved",
            "reason": "Client has not yet confirmed the budget owner.",
        }
        contract["data_models"] = {
            "status": "unresolved",
            "reason": "Client has not described any data entities yet.",
        }
        result = validate(contract)
        self.assertEqual(result.state, schema.REQUIRES_HUMAN_REVIEW)
        self.assertEqual(result.gaps, [])
        self.assertEqual(len(result.unresolved_markers), 2)

    def test_the_ba_must_not_fabricate_to_pass_unresolved_fields_cannot_be_faked_as_passed(self):
        contract = _base_valid_contract()
        contract["business_case"] = "Totally real business case."
        result = validate(contract)
        self.assertEqual(result.state, schema.PASSED)


class MissingAndMalformedTests(unittest.TestCase):
    def test_missing_required_field_fails(self):
        contract = _base_valid_contract()
        del contract["business_case"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "missing_field" and g.field_path == "business_case" for g in result.gaps))

    def test_malformed_field_type_fails(self):
        contract = _base_valid_contract()
        contract["tasks"] = "not a list"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_field" and g.field_path == "tasks" for g in result.gaps))

    def test_non_dict_root_fails(self):
        result = validate(["not", "a", "dict"])
        self.assertEqual(result.state, schema.FAILED)

    def test_unsupported_schema_version_fails(self):
        contract = _base_valid_contract()
        contract["schema_version"] = "0.9"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "unsupported_schema_version" for g in result.gaps))


class DuplicateAndBrokenReferenceTests(unittest.TestCase):
    def test_duplicate_id_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"].append(
            {"id": "FR-001", "text": "Duplicate id.", "source_feature": "login"}
        )
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "duplicate_id" and g.field_path == "functional_requirements" for g in result.gaps))

    def test_broken_reference_to_nonexistent_fr_fails(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = ["FR-999"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "broken_reference" for g in result.gaps))

    def test_broken_reference_to_retired_fr_fails(self):
        contract = _base_valid_contract()
        contract["retired_ids"] = ["FR-001"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "broken_reference" and "retired" in g.detail for g in result.gaps))

    def test_orphan_functional_requirement_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"].append(
            {"id": "FR-002", "text": "No story links to this.", "source_feature": "reports"}
        )
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "orphan" and "FR-002" in g.related_ids for g in result.gaps))

    def test_orphan_user_story_fails(self):
        contract = _base_valid_contract()
        contract["acceptance_criteria"][0]["id"] = "AC-001"  # keep AC-001 on US-001
        contract["functional_requirements"].append(
            {"id": "FR-002", "text": "Second feature.", "source_feature": "reports"}
        )
        contract["user_stories"].append(
            {"id": "US-002", "fr_ids": ["FR-002"], "as_a": "x", "i_want": "y", "so_that": "z"}
        )
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "orphan" and "US-002" in g.related_ids for g in result.gaps))


class NfrConfirmationTests(unittest.TestCase):
    def test_empty_nfr_without_confirmation_fails(self):
        contract = _base_valid_contract()
        contract["non_functional_requirements"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "unconfirmed_empty_nfr" for g in result.gaps))

    def test_empty_nfr_with_valid_confirmation_passes(self):
        contract = _base_valid_contract()
        contract["non_functional_requirements"] = []
        contract["non_functional_requirements_confirmation"] = {
            "status": "confirmed_empty",
            "reason": "Client explicitly stated no NFRs beyond defaults apply.",
        }
        result = validate(contract)
        self.assertEqual(result.state, schema.PASSED)

    def test_empty_nfr_with_malformed_confirmation_fails(self):
        contract = _base_valid_contract()
        contract["non_functional_requirements"] = []
        contract["non_functional_requirements_confirmation"] = {"status": "confirmed_empty"}
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)


class EmptyListWithoutMarkerTests(unittest.TestCase):
    def test_empty_tasks_without_unresolved_marker_fails(self):
        contract = _base_valid_contract()
        contract["tasks"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "unconfirmed_empty" and g.field_path == "tasks" for g in result.gaps))

    def test_empty_data_models_without_unresolved_marker_fails(self):
        contract = _base_valid_contract()
        contract["data_models"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "unconfirmed_empty" and g.field_path == "data_models" for g in result.gaps))

    def test_empty_data_models_with_unresolved_marker_requires_human_review(self):
        contract = _base_valid_contract()
        contract["data_models"] = {
            "status": "unresolved",
            "reason": "Client has not described any entities yet.",
        }
        result = validate(contract)
        self.assertEqual(result.state, schema.REQUIRES_HUMAN_REVIEW)


class FlaggedConcernTests(unittest.TestCase):
    def test_open_flagged_concern_prevents_pass(self):
        contract = _base_valid_contract()
        contract[schema.HUMAN_FLAGGED_CONCERNS_FIELD] = [
            {
                "type": "potential_contradiction",
                "description": "FR-001 conflicts with an earlier statement.",
                "related_ids": ["FR-001"],
                "resolved": False,
            }
        ]
        result = validate(contract)
        self.assertEqual(result.state, schema.REQUIRES_HUMAN_REVIEW)

    def test_resolved_flagged_concern_allows_pass(self):
        contract = _base_valid_contract()
        contract[schema.HUMAN_FLAGGED_CONCERNS_FIELD] = [
            {
                "type": "ambiguity",
                "description": "Previously ambiguous phrasing, now clarified.",
                "related_ids": ["FR-001"],
                "resolved": True,
            }
        ]
        result = validate(contract)
        self.assertEqual(result.state, schema.PASSED)

    def test_malformed_concern_fails(self):
        contract = _base_valid_contract()
        contract[schema.HUMAN_FLAGGED_CONCERNS_FIELD] = [{"type": "not_a_real_type"}]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)


class LlmCannotOverrideValidatorStateTests(unittest.TestCase):
    def test_llm_supplied_passed_state_on_broken_contract_is_ignored(self):
        contract = _base_valid_contract()
        del contract["business_case"]
        contract["validation"] = {"state": "passed", "unresolved_gaps": []}
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertNotEqual(result.state, contract["validation"]["state"])


class DeepCopyIsolationTests(unittest.TestCase):
    def test_validate_does_not_mutate_input_contract(self):
        contract = _base_valid_contract()
        snapshot = copy.deepcopy(contract)
        validate(contract)
        self.assertEqual(contract, snapshot)


# ---------------------------------------------------------------------------
# Phase 2.3 hardening — regression tests for each confirmed issue
# ---------------------------------------------------------------------------

class EmptyCoreArrayTests(unittest.TestCase):
    """Review item 1: FR/US/AC must each contain at least one valid item."""

    def test_empty_functional_requirements_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"] = []
        contract["user_stories"] = []
        contract["acceptance_criteria"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "empty_required_list" and g.field_path == "functional_requirements" for g in result.gaps))

    def test_empty_user_stories_fails(self):
        contract = _base_valid_contract()
        contract["user_stories"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "empty_required_list" and g.field_path == "user_stories" for g in result.gaps))

    def test_empty_acceptance_criteria_fails(self):
        contract = _base_valid_contract()
        contract["acceptance_criteria"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "empty_required_list" and g.field_path == "acceptance_criteria" for g in result.gaps))

    def test_all_three_empty_simultaneously_reports_all_three_gaps_not_just_one(self):
        contract = _base_valid_contract()
        contract["functional_requirements"] = []
        contract["user_stories"] = []
        contract["acceptance_criteria"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        flagged_fields = {g.field_path for g in result.gaps if g.type == "empty_required_list"}
        self.assertEqual(flagged_fields, {"functional_requirements", "user_stories", "acceptance_criteria"})


class StrictIdFormatTests(unittest.TestCase):
    """Review item 2: FR-NNN / US-NNN / AC-NNN enforced exactly."""

    def test_non_numeric_suffix_fr_id_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"][0]["id"] = "FR-abc"
        contract["user_stories"][0]["fr_ids"] = ["FR-abc"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_id" and g.field_path == "functional_requirements" for g in result.gaps))

    def test_wrong_digit_count_fails(self):
        for bad_id in ("FR-1", "FR-01", "FR-0001"):
            with self.subTest(bad_id=bad_id):
                contract = _base_valid_contract()
                contract["functional_requirements"][0]["id"] = bad_id
                result = validate(contract)
                self.assertEqual(result.state, schema.FAILED)
                self.assertTrue(any(g.type == "malformed_id" for g in result.gaps))

    def test_wrong_prefix_fails(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["id"] = "FR-002"  # a US item using the FR prefix
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_id" and g.field_path == "user_stories" for g in result.gaps))

    def test_trailing_garbage_after_valid_id_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"][0]["id"] = "FR-001x"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_id" for g in result.gaps))


class MalformedFrIdsTests(unittest.TestCase):
    """Review item 3: fr_ids as a string must be a clean malformed_field gap."""

    def test_fr_ids_as_string_reports_malformed_field_not_broken_reference(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = "FR-001"  # string, not a list
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        gap_types = {g.type for g in result.gaps}
        self.assertIn("malformed_field", gap_types)
        # The misleading behavior being fixed: iterating a string yields
        # its characters ('F', 'R', '-', ...) as fake "broken" FR ids.
        self.assertFalse(
            any(g.type == "broken_reference" and g.related_ids and g.related_ids[1] in ("F", "R", "-", "0", "1")
                for g in result.gaps)
        )

    def test_fr_ids_as_int_does_not_crash(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = 42
        result = validate(contract)  # must not raise
        self.assertEqual(result.state, schema.FAILED)

    def test_fr_ids_with_non_string_entries_reports_malformed_field(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = ["FR-001", 42, None]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_field" and g.field_path == "user_stories.fr_ids" for g in result.gaps))


class MalformedRetiredIdsTests(unittest.TestCase):
    """Review item 4: retired_ids must be a list of valid, unique IDs."""

    def test_retired_ids_as_string_fails_instead_of_silently_passing(self):
        contract = _base_valid_contract()
        contract["retired_ids"] = "FR-001"  # bug under test: set("FR-001") used to silently "work"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_field" and g.field_path == "retired_ids" for g in result.gaps))

    def test_retired_ids_as_string_does_not_crash(self):
        contract = _base_valid_contract()
        contract["retired_ids"] = "FR-001"
        validate(contract)  # must not raise

    def test_retired_ids_with_invalid_id_format_fails(self):
        contract = _base_valid_contract()
        contract["retired_ids"] = ["not-an-id"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_id" and g.field_path == "retired_ids" for g in result.gaps))

    def test_duplicate_retired_ids_fail(self):
        contract = _base_valid_contract()
        contract["retired_ids"] = ["FR-999", "FR-999"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "duplicate_id" and g.field_path == "retired_ids" for g in result.gaps))

    def test_retired_ids_absent_defaults_to_empty_and_passes(self):
        contract = _base_valid_contract()
        self.assertNotIn("retired_ids", contract)
        result = validate(contract)
        self.assertEqual(result.state, schema.PASSED)


class IncompleteItemTests(unittest.TestCase):
    """Review item 5: structural completeness of every item type."""

    def test_functional_requirement_missing_text_fails(self):
        contract = _base_valid_contract()
        del contract["functional_requirements"][0]["text"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "functional_requirements" for g in result.gaps))

    def test_functional_requirement_blank_source_feature_fails(self):
        contract = _base_valid_contract()
        contract["functional_requirements"][0]["source_feature"] = "   "
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "functional_requirements" for g in result.gaps))

    def test_nfr_missing_text_fails(self):
        contract = _base_valid_contract()
        del contract["non_functional_requirements"][0]["text"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "non_functional_requirements" for g in result.gaps))

    def test_nfr_missing_id_fails(self):
        contract = _base_valid_contract()
        del contract["non_functional_requirements"][0]["id"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "non_functional_requirements" for g in result.gaps))

    def test_user_story_missing_as_a_fails(self):
        contract = _base_valid_contract()
        del contract["user_stories"][0]["as_a"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "user_stories" for g in result.gaps))

    def test_user_story_empty_fr_ids_list_fails(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "user_stories.fr_ids" for g in result.gaps))

    def test_acceptance_criterion_missing_given_fails(self):
        contract = _base_valid_contract()
        del contract["acceptance_criteria"][0]["given"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "acceptance_criteria" for g in result.gaps))

    def test_acceptance_criterion_missing_story_id_fails(self):
        contract = _base_valid_contract()
        del contract["acceptance_criteria"][0]["story_id"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "acceptance_criteria" for g in result.gaps))

    def test_acceptance_criterion_story_id_wrong_type_fails_cleanly(self):
        contract = _base_valid_contract()
        contract["acceptance_criteria"][0]["story_id"] = 123  # int instead of string
        result = validate(contract)  # must not raise
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_field" and g.field_path == "acceptance_criteria.story_id" for g in result.gaps))


class DataModelStructureTests(unittest.TestCase):
    """Review item 5 (data models) + item 10."""

    def test_data_model_missing_entity_name_fails(self):
        contract = _base_valid_contract()
        del contract["data_models"][0]["entity"]
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "data_models" for g in result.gaps))

    def test_data_model_attribute_missing_type_fails(self):
        contract = _base_valid_contract()
        contract["data_models"][0]["attributes"] = [{"name": "email"}]  # no "type"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "data_models" for g in result.gaps))

    def test_data_model_attributes_wrong_type_fails_cleanly(self):
        contract = _base_valid_contract()
        contract["data_models"][0]["attributes"] = "email:string"  # string, not list
        result = validate(contract)  # must not raise
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "malformed_field" for g in result.gaps))

    def test_data_model_relationship_missing_to_entity_fails(self):
        contract = _base_valid_contract()
        contract["data_models"][0]["relationships"] = [{"type": "has_many"}]  # no "to_entity"
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)
        self.assertTrue(any(g.type == "incomplete_item" and g.field_path == "data_models" for g in result.gaps))

    def test_data_model_relationships_wrong_type_fails_cleanly(self):
        contract = _base_valid_contract()
        contract["data_models"][0]["relationships"] = "has_many:Order"
        result = validate(contract)  # must not raise
        self.assertEqual(result.state, schema.FAILED)

    def test_data_model_empty_relationships_list_is_fine(self):
        # "no relationships" is a legitimate state, distinct from a
        # missing/malformed relationships field.
        contract = _base_valid_contract()
        contract["data_models"][0]["relationships"] = []
        result = validate(contract)
        self.assertEqual(result.state, schema.PASSED)


class CrashSafetyTests(unittest.TestCase):
    """
    Review item 9: malformed inputs must never raise. Each case below
    calls validate() directly with no try/except around it — if
    validate() raised, the test itself would error out (not just fail),
    which is the strongest available proof of "no uncaught exception".
    """

    def test_everything_wrong_at_once_does_not_crash(self):
        chaos = {
            "schema_version": "1.0",
            "project": "not a dict",
            "objectives_and_goals": 1,
            "tasks": None,
            "business_case": 3.14,
            "functional_requirements": "FR-001",
            "non_functional_requirements": {"not": "a list"},
            "user_stories": [{"id": "US-001", "fr_ids": "FR-001"}],
            "acceptance_criteria": [{"id": 123, "story_id": ["nested", "list"]}],
            "in_scope_features": {},
            "data_models": [{"entity": 42, "attributes": "x", "relationships": 7}],
            "retired_ids": {"a": "b"},
            schema.HUMAN_FLAGGED_CONCERNS_FIELD: "not a list",
        }
        result = validate(chaos)  # must not raise
        self.assertEqual(result.state, schema.FAILED)
        self.assertGreater(len(result.gaps), 0)

    def test_empty_dict_does_not_crash(self):
        result = validate({})
        self.assertEqual(result.state, schema.FAILED)

    def test_none_contract_does_not_crash(self):
        result = validate(None)
        self.assertEqual(result.state, schema.FAILED)

    def test_nested_none_values_do_not_crash(self):
        contract = _base_valid_contract()
        contract["user_stories"][0]["fr_ids"] = None
        contract["acceptance_criteria"][0]["story_id"] = None
        contract["retired_ids"] = None
        result = validate(contract)
        self.assertEqual(result.state, schema.FAILED)


if __name__ == "__main__":
    unittest.main()
