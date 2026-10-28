"""Shared state passed between LangGraph nodes."""
import operator
from typing import Annotated, TypedDict

class State(TypedDict, total=False):
    # run identity (Phase 3B.2): set once by intro(), never regenerated on
    # resume, since intro() only runs once at the start of a fresh graph
    # invocation (resuming via Command(resume=...) re-enters the graph at
    # the interrupted node's checkpoint, not at START/intro again).
    run_id: str              # unique per artifact-producing execution
    output_dir: str          # this run's resolved, isolated output directory
    # canonical adapter/validator integration (Phase 3B.3): additive only,
    # never read by any pre-existing node.
    legacy_contract: dict    # the exact dict write_requirements_json wrote to
                              # requirements.json, exposed so canonical_validate
                              # doesn't have to re-derive it from scratch
    canonical_status: str    # one of ba_contract_prototype.schema's validation
                              # states, or the literal string "mapping_error"
                              # if adapter.adapt() raised MappingError
    canonical_error: str     # populated only when canonical_status == "mapping_error"
    canonical_gaps: list     # the canonical validator's gap list (as dicts), if any
    # RAG integration (Phase 3C.1): the knowledge-base chunks retrieved for
    # the most recent analyse_requirements call, as plain dicts
    # ({text, source, chunk_id, score, metadata}). Always a list — empty
    # when retrieval was unavailable or found nothing relevant, never
    # absent, so downstream code can treat it uniformly. Set once per
    # analyse_requirements call (including repair re-runs, which refresh it).
    retrieved_evidence: list
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
