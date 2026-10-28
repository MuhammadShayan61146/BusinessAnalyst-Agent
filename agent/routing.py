"""Small routing helpers used by the graph."""
from config.constants import QUESTIONS, WRITERS

def pick_number(reply, count):
    """'2' -> 1 (a list position). Returns None if the reply is not a valid number."""
    reply = reply.strip()
    if reply.isdigit() and 1 <= int(reply) <= count:
        return int(reply) - 1
    return None


def route_after_evaluate(state):
    # A conditional edge is a plain function that returns the NAME of the next node.
    if state["verdict"] == "vague" and state["followup_count"] == 0:
        return "ask_followup"
    return "store_answer"


def route_after_store(state):
    if state["editing"]:
        return "confirm_summary"
    if QUESTIONS[state["q_index"] - 1]["key"] == "features":
        return "suggest_features"
    if state["q_index"] < len(QUESTIONS):
        return "ask_question"
    return "present_themes"


def route_after_features(state):
    return "ask_question" if state["q_index"] < len(QUESTIONS) else "present_themes"


def route_after_theme(state):
    return "custom_colors" if state["theme"]["name"] == "custom" else "present_logo_styles"


def route_after_logo(state):
    return "confirm_summary" if state["logo"] else "present_logo_styles"


def route_after_confirm(state):
    d = state["decision"]
    if d == "yes":
        return "build_requirements_json"
    if d == "edit theme":
        return "present_themes"
    if d == "edit logo":
        return "present_logo_styles"
    if state["editing"]:
        return "ask_question"
    return "confirm_summary"


def route_after_validate(state):
    return state["next_step"]


def route_after_review(state):
    r = state["review"]
    if r == "approve":
        return WRITERS                  # returning a LIST runs all of them in parallel
    if r.startswith("change stories"):
        return "generate_user_stories"
    if r.startswith("change criteria"):
        return "generate_acceptance_criteria"
    return "review_stories"
