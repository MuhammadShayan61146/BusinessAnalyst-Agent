"""
Tests against the REAL, unmodified agent.routing module. These
functions import only config.constants (no external deps), so no
stubbing is required here.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Business-Analyst-Agent-main"))

import agent.routing as routing  # noqa: E402  (real production source, unmodified)


class PickNumberTests(unittest.TestCase):
    def test_valid_selection_returns_zero_based_index(self):
        self.assertEqual(routing.pick_number("2", 3), 1)

    def test_lower_bound_valid(self):
        self.assertEqual(routing.pick_number("1", 3), 0)

    def test_upper_bound_valid(self):
        self.assertEqual(routing.pick_number("3", 3), 2)

    def test_zero_is_invalid_malformed_input_handled_gracefully(self):
        self.assertIsNone(routing.pick_number("0", 3))

    def test_out_of_range_is_invalid(self):
        self.assertIsNone(routing.pick_number("4", 3))

    def test_non_numeric_is_invalid_malformed_input_handled_gracefully(self):
        self.assertIsNone(routing.pick_number("abc", 3))

    def test_whitespace_padded_valid_number_still_works(self):
        self.assertEqual(routing.pick_number("  2  ", 3), 1)

    def test_empty_string_is_invalid(self):
        self.assertIsNone(routing.pick_number("", 3))


class RouteAfterEvaluateTests(unittest.TestCase):
    def test_vague_with_no_followup_yet_asks_followup(self):
        self.assertEqual(routing.route_after_evaluate({"verdict": "vague", "followup_count": 0}), "ask_followup")

    def test_vague_after_followup_used_proceeds_to_store(self):
        self.assertEqual(routing.route_after_evaluate({"verdict": "vague", "followup_count": 1}), "store_answer")

    def test_clear_proceeds_to_store(self):
        self.assertEqual(routing.route_after_evaluate({"verdict": "clear", "followup_count": 0}), "store_answer")


class RouteAfterConfirmTests(unittest.TestCase):
    def test_yes_proceeds_to_build_requirements_json(self):
        self.assertEqual(routing.route_after_confirm({"decision": "yes", "editing": False}), "build_requirements_json")

    def test_edit_theme_routes_to_present_themes(self):
        self.assertEqual(routing.route_after_confirm({"decision": "edit theme", "editing": False}), "present_themes")

    def test_edit_logo_routes_to_present_logo_styles(self):
        self.assertEqual(routing.route_after_confirm({"decision": "edit logo", "editing": False}), "present_logo_styles")

    def test_anything_else_with_editing_true_routes_to_ask_question(self):
        self.assertEqual(routing.route_after_confirm({"decision": "garbled", "editing": True}), "ask_question")

    def test_anything_else_without_editing_loops_confirm_summary(self):
        self.assertEqual(routing.route_after_confirm({"decision": "garbled", "editing": False}), "confirm_summary")


class RouteAfterValidateTests(unittest.TestCase):
    def test_passes_through_next_step_verbatim(self):
        self.assertEqual(routing.route_after_validate({"next_step": "review_stories"}), "review_stories")


class RouteAfterReviewTests(unittest.TestCase):
    def test_approve_returns_the_writers_list(self):
        from config.constants import WRITERS
        self.assertEqual(routing.route_after_review({"review": "approve"}), WRITERS)

    def test_change_stories_routes_back(self):
        self.assertEqual(
            routing.route_after_review({"review": "change stories: add admin role"}),
            "generate_user_stories",
        )

    def test_change_criteria_routes_back(self):
        self.assertEqual(
            routing.route_after_review({"review": "change criteria: tighten wording"}),
            "generate_acceptance_criteria",
        )

    def test_unrecognized_reply_loops_review(self):
        self.assertEqual(routing.route_after_review({"review": "huh?"}), "review_stories")


if __name__ == "__main__":
    unittest.main()
