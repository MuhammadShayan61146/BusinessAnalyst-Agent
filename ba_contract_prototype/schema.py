"""
Canonical Business Analyst (BA) contract schema.

Scope :
    This module defines ONLY the data shape of the BA contract and the
    forward-compatible workflow state vocabulary. It performs no LLM
    calls, touches no file on disk, and imports nothing from the legacy
    `softwaredevelopmentapi` package. It is intentionally isolated so it
    can be unit-tested with zero dependencies and zero API keys.

   
"""

from __future__ import annotations

SCHEMA_VERSION = "1.0"


NOT_YET_VALIDATED = "not_yet_validated"
FAILED = "failed"
PASSED = "passed"
REQUIRES_HUMAN_REVIEW = "requires_human_review"

VALIDATION_STATES = frozenset(
    {NOT_YET_VALIDATED, FAILED, PASSED, REQUIRES_HUMAN_REVIEW}
)


WORKFLOW_HUMAN_APPROVED = "human_approved"            
WORKFLOW_AWAITING_ARCHITECT = "awaiting_architect"     
WORKFLOW_ARCHITECT_FEEDBACK = "architect_feedback"     
WORKFLOW_COMPLETED = "completed"                       
WORKFLOW_TERMINAL_REVIEW = "terminal_review_required"  

WORKFLOW_STATES = frozenset(
    {
        WORKFLOW_HUMAN_APPROVED,
        WORKFLOW_AWAITING_ARCHITECT,
        WORKFLOW_ARCHITECT_FEEDBACK,
        WORKFLOW_COMPLETED,
        WORKFLOW_TERMINAL_REVIEW,
    }
)

UNRESOLVED_STATUS = "unresolved"


def is_unresolved_marker(value) -> bool:
    """True if `value` is a well-formed unresolved marker (Task 2/A)."""
    return (
        isinstance(value, dict)
        and value.get("status") == UNRESOLVED_STATUS
        and isinstance(value.get("reason"), str)
        and value.get("reason").strip() != ""
    )



NFR_CONFIRMED_EMPTY_STATUS = "confirmed_empty"


def is_nfr_confirmation(value) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") == NFR_CONFIRMED_EMPTY_STATUS
        and isinstance(value.get("reason"), str)
        and value.get("reason").strip() != ""
    )



HUMAN_FLAGGED_CONCERNS_FIELD = "human_flagged_concerns"
CONCERN_TYPES = frozenset({"potential_contradiction", "ambiguity"})


def is_valid_concern(value) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") in CONCERN_TYPES
        and isinstance(value.get("description"), str)
        and value.get("description").strip() != ""
        and isinstance(value.get("related_ids"), list)
        and value.get("resolved", False) in (True, False)
    )



import re as _re

ID_PREFIXES = {
    "functional_requirements": "FR",
    "user_stories": "US",
    "acceptance_criteria": "AC",
}

ID_PATTERNS = {name: _re.compile(rf"^{prefix}-\d{{3}}$") for name, prefix in ID_PREFIXES.items()}
# Any prefix, for validating entries of "retired_ids" (which may retire
# an id originally minted under any of the three arrays).
ANY_ID_PATTERN = _re.compile(r"^(FR|US|AC)-\d{3}$")


def is_well_formed_id(value, field_name: str) -> bool:
    """True if `value` is a string matching the strict ID format for `field_name`."""
    if not isinstance(value, str):
        return False
    pattern = ID_PATTERNS.get(field_name)
    if pattern is None:
        return False
    return bool(pattern.fullmatch(value))


def is_well_formed_any_id(value) -> bool:
    """True if `value` is a string matching FR-NNN / US-NNN / AC-NNN (any prefix)."""
    return isinstance(value, str) and bool(ANY_ID_PATTERN.fullmatch(value))

REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "project",
    "objectives_and_goals",
    "tasks",
    "business_case",
    "functional_requirements",
    "non_functional_requirements",
    "user_stories",
    "acceptance_criteria",
    "in_scope_features",
    "data_models",
)


LIST_OR_UNRESOLVED_FIELDS = (
    "objectives_and_goals",
    "tasks",
    "in_scope_features",
    "data_models",
)


STRING_OR_UNRESOLVED_FIELDS = (
    "business_case",
)

MIN_REQUIRED_ITEMS = 1

FR_REQUIRED_STRING_FIELDS = ("text", "source_feature")
NFR_REQUIRED_STRING_FIELDS = ("text",)
US_REQUIRED_STRING_FIELDS = ("as_a", "i_want", "so_that")
AC_REQUIRED_STRING_FIELDS = ("given", "when", "then")
DATA_ENTITY_REQUIRED_STRING_FIELDS = ("entity",)
DATA_ATTRIBUTE_REQUIRED_STRING_FIELDS = ("name", "type")
DATA_RELATIONSHIP_REQUIRED_STRING_FIELDS = ("to_entity", "type")
