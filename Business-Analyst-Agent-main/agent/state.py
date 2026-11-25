"""Shared state passed between LangGraph nodes."""
import operator
from typing import Annotated, TypedDict

class State(TypedDict, total=False):
    
    run_id: str              # unique per artifact-producing execution
    output_dir: str          
    legacy_contract: dict    
    canonical_status: str    
    canonical_error: str     
    canonical_gaps: list    
    retrieved_evidence: list
    # triage (ambiguity/consistency) findings for the human reviewer, and the
    # subset converted into canonical human_flagged_concerns
    triage_findings: list
    canonical_concerns: list
    # phase 1: questions
    q_index: int            # which question we are on
    last_answer: str
    verdict: str            # "clear" or "vague"
    followup_question: str
    followup_count: int
    answers: dict           # {"name": "...", "features": "...", ...}
    suggested: list         # features the LLM thinks the client forgot
    editing: bool           # True when the client chose "edit N"
    # phase 2: UI
    theme: dict
    logo_style: str
    logos: list
    logo: str
    # phase 3: confirmation
    decision: str
    # phase 4: analysis
    analysis: dict
    stories: list
    criteria: list
    gaps: str               # problems found by validate (sent back to the LLM to fix)
    leftover: str           # problems still left after the repair limit
    next_step: str
    repairs: dict           # how many repairs we did: {"fr": 0, "story": 0, "criteria": 0}
    # phase 5: review
    review: str
    feedback: str
    # phase 6: files (Annotated + operator.add means "append, don't overwrite")
    files: Annotated[list, operator.add]
