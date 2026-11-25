
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

from _stubs import install_stubs  # noqa: E402
install_stubs()

import agent.nodes as nodes  # noqa: E402  (real production source, unmodified)


def _state(features="login, checkout", frs=None, stories=None, criteria=None, repairs=None):
    return {
        "answers": {"features": features},
        "analysis": {"functional_requirements": frs or []},
        "stories": stories or [],
        "criteria": criteria or [],
        "repairs": repairs or {"fr": 0, "story": 0, "criteria": 0},
    }


class ValidateCleanPassTests(unittest.TestCase):
    def test_fully_covered_state_returns_review_stories_with_no_gaps(self):
        state = _state(
            features="login, checkout",
            frs=[{"id": "FR-1", "feature": "login"}, {"id": "FR-2", "feature": "checkout"}],
            stories=[{"id": "US-1", "fr_ids": ["FR-1"]}, {"id": "US-2", "fr_ids": ["FR-2"]}],
            criteria=[{"story_id": "US-1"}, {"story_id": "US-2"}],
        )
        result = nodes.validate(state)
        self.assertEqual(result["gaps"], "")
        self.assertEqual(result["leftover"], "")
        self.assertEqual(result["next_step"], "review_stories")


class ValidateRepairRoutingTests(unittest.TestCase):
    def test_missing_fr_coverage_routes_back_to_analyse_requirements_and_increments_repair_count(self):
        state = _state(
            features="login, checkout",
            frs=[{"id": "FR-1", "feature": "login"}],  # "checkout" feature has no FR
            stories=[{"id": "US-1", "fr_ids": ["FR-1"]}],
            criteria=[{"story_id": "US-1"}],
        )
        result = nodes.validate(state)
        self.assertEqual(result["next_step"], "analyse_requirements")
        self.assertIn("checkout", result["gaps"])
        self.assertEqual(result["repairs"]["fr"], 1)
        # other counters untouched this call
        self.assertEqual(result["repairs"]["story"], 0)
        self.assertEqual(result["repairs"]["criteria"], 0)

    def test_missing_story_coverage_routes_back_to_generate_user_stories(self):
        state = _state(
            features="login",
            frs=[{"id": "FR-1", "feature": "login"}],
            stories=[],  # no story links FR-1
            criteria=[],
        )
        result = nodes.validate(state)
        self.assertEqual(result["next_step"], "generate_user_stories")
        self.assertIn("FR-1", result["gaps"])

    def test_missing_criteria_coverage_routes_back_to_generate_acceptance_criteria(self):
        state = _state(
            features="login",
            frs=[{"id": "FR-1", "feature": "login"}],
            stories=[{"id": "US-1", "fr_ids": ["FR-1"]}],
            criteria=[],  # US-1 has no criteria
        )
        result = nodes.validate(state)
        self.assertEqual(result["next_step"], "generate_acceptance_criteria")
        self.assertIn("US-1", result["gaps"])

    def test_repair_budget_of_two_is_enforced_then_falls_through_to_leftover(self):
        state = _state(
            features="checkout",
            frs=[],  # permanently missing FR for "checkout"
            stories=[],
            criteria=[],
            repairs={"fr": 2, "story": 0, "criteria": 0},  # budget already exhausted for 'fr'
        )
        result = nodes.validate(state)
        # fr budget exhausted -> falls through to the next kind ('story'),
        # which is also unsatisfied (no FR exists to link), confirmed by
        # reading the real loop order ["fr", "story", "criteria"].
        self.assertIn(result["next_step"], ("generate_user_stories", "review_stories"))

    def test_all_three_budgets_exhausted_reports_leftover_and_proceeds_to_review(self):
        state = _state(
            features="checkout",
            frs=[],
            stories=[],
            criteria=[],
            repairs={"fr": 2, "story": 2, "criteria": 2},
        )
        result = nodes.validate(state)
        self.assertEqual(result["next_step"], "review_stories")
        self.assertNotEqual(result["leftover"], "")


class ValidateUntestableWithoutChangesTests(unittest.TestCase):
    """
    Documents, rather than silently skips, a behavior this phase
    cannot cover: validate() has no defensive handling for malformed
    or missing state keys (e.g. a missing 'repairs' key raises
    KeyError). This is consistent with the Phase 2.1 finding that the
    legacy/real BusinessAnalyst pipeline has no built-in malformed-
    input handling. Testing "malformed input handling" here would
    require either modifying agent/nodes.py (forbidden this phase) or
    asserting that it crashes, which documents a limitation rather
    than a passing behavior.
    """

    def test_missing_repairs_key_raises_keyerror_this_is_documented_not_fixed(self):
        state = {
            "answers": {"features": "login"},
            "analysis": {"functional_requirements": []},
            "stories": [],
            "criteria": [],
            # "repairs" intentionally omitted
        }
        with self.assertRaises(KeyError):
            nodes.validate(state)


if __name__ == "__main__":
    unittest.main()
