"""Workflow nodes: each function performs one step of the conversation."""
import json

from langgraph.types import interrupt
from config.constants import QUESTIONS, SKIP_WORDS, PRESETS, LOGO_STYLES
from config.settings import new_run_id, make_run_output_dir
from services.llm_service import ask_llm_json
from services.document_service import save_doc
from agent.routing import pick_number

def intro(state):
    print("Hello! I am your Business Analyst. I will ask a few questions about your project.")
    # Run identity (Phase 3B.2): generated once, here, at the start of a
    # fresh graph invocation. This node has no incoming edge other than
    # START (see agent/graph.py), so Command(resume=...) never re-enters
    # here — a resumed conversation keeps whatever run_id/output_dir was
    # set on its first pass through intro(), satisfying "do not create a
    # new artifact directory every time an interrupt is resumed."
    run_id = new_run_id()
    output_dir = make_run_output_dir(run_id)
    return {"q_index": 0, "followup_count": 0, "answers": {}, "editing": False,
            "repairs": {"fr": 0, "story": 0, "criteria": 0}, "feedback": "",
            "run_id": run_id, "output_dir": output_dir}


def ask_question(state):
    q = QUESTIONS[state["q_index"]]
    hint = "  (optional: type skip)" if q.get("optional") else ""
    # interrupt() pauses the graph and shows this to the human.
    # When the human replies, interrupt() returns the reply.
    answer = interrupt({"question": q["text"] + hint, "options": q["options"]})
    return {"last_answer": answer, "followup_count": 0}


def evaluate_answer(state):
    q = QUESTIONS[state["q_index"]]
    answer = state["last_answer"].strip()

    idx = pick_number(answer, len(q["options"]))
    if idx is not None:                                   # picked an option, clearly fine
        return {"last_answer": q["options"][idx], "verdict": "clear"}
    if q.get("optional") and answer.lower() in SKIP_WORDS:
        return {"last_answer": "Not specified", "verdict": "clear"}

    result = ask_llm_json(
        f"Question: {q['text']}\nClient answer: {answer}\n"
        'Is this clear enough to build software from? Return '
        '{"verdict": "clear" or "vague", "followup": "one short clarifying question, or empty"}'
    )
    return {"last_answer": answer, "verdict": result["verdict"],
            "followup_question": result.get("followup", "")}


def ask_followup(state):
    extra = interrupt({"question": state["followup_question"], "options": []})
    return {"last_answer": state["last_answer"] + " | " + extra,
            "followup_count": state["followup_count"] + 1}


def store_answer(state):
    q = QUESTIONS[state["q_index"]]
    update = {"answers": {**state["answers"], q["key"]: state["last_answer"]},
              "q_index": state["q_index"] + 1}
    if q["key"] == "features":
        # The LLM call happens HERE, not inside the interrupt node (see lesson on interrupts).
        update["suggested"] = ask_llm_json(
            f"Project: {state['answers']['name']} - {state['answers']['description']}\n"
            f"Features listed: {state['last_answer']}\n"
            "Suggest 3 important features the client may have forgotten. "
            "Return a JSON list of 3 short strings."
        )
    return update


def suggest_features(state):
    reply = interrupt({"question": "Did we miss anything? Pick numbers like 1,3 or type none.",
                       "options": state["suggested"]})
    answers = dict(state["answers"])
    for part in reply.split(","):
        idx = pick_number(part, len(state["suggested"]))
        if idx is not None:
            answers["features"] += ", " + state["suggested"][idx]
    return {"answers": answers}


def present_themes(state):
    names = list(PRESETS)
    options = [f"{n} ({PRESETS[n]['primary']})" for n in names]
    reply = interrupt({"question": "Pick a theme number, or type custom.", "options": options})
    if reply.strip().lower() == "custom":
        return {"theme": {"name": "custom"}}
    idx = pick_number(reply, len(names))
    idx = 0 if idx is None else idx                       # bad input -> first preset
    return {"theme": {"name": names[idx], **PRESETS[names[idx]]}}


def custom_colors(state):
    reply = interrupt({"question": "Type primary and background hex colors, e.g. #1E6FD9, #FFFFFF",
                       "options": []})
    parts = [c.strip() for c in reply.split(",")] + ["", ""]
    return {"theme": {"name": "custom", "primary": parts[0] or "#1E6FD9",
                      "background": parts[1] or "#FFFFFF"}}


def present_logo_styles(state):
    reply = interrupt({"question": "Pick a logo style.", "options": LOGO_STYLES})
    idx = pick_number(reply, len(LOGO_STYLES))
    return {"logo_style": LOGO_STYLES[0 if idx is None else idx]}


def generate_logos(state):
    theme = state["theme"]
    output_dir = state["output_dir"]
    logos = ask_llm_json(
        f"Project: {state['answers']['name']} - {state['answers']['description']}\n"
        f"Style: {state['logo_style']}. Colors: {theme['primary']} and {theme['background']}.\n"
        "Create 3 different simple logo concepts as SVG. "
        "Return a JSON list of 3 strings, each a full <svg>...</svg>."
    )
    # NOTE (Phase 3B.2, design requirement 3): if the client rejects all 3
    # options and loops back here (pick_logo -> present_logo_styles ->
    # generate_logos again), this intentionally OVERWRITES
    # logo_option_1..3.svg within the SAME run's output_dir. That is the
    # existing, intended behavior (showing a new alternative set replaces
    # the previous one) — preserved unchanged, only now scoped to the
    # run's own directory instead of the single global one.
    for i, svg in enumerate(logos, 1):
        with open(f"{output_dir}/logo_option_{i}.svg", "w") as f:
            f.write(svg)
    return {"logos": logos}


def pick_logo(state):
    output_dir = state["output_dir"]
    reply = interrupt({"question": f"Open {output_dir}/logo_option_1..3.svg, then pick 1-3 or type another.",
                       "options": []})
    idx = pick_number(reply, len(state["logos"]))
    if idx is None:
        return {"logo": ""}                               # empty means "show another style"
    with open(f"{output_dir}/logo.svg", "w") as f:
        f.write(state["logos"][idx])
    return {"logo": state["logos"][idx]}


def confirm_summary(state):
    lines = [f"{i + 1}. {q['text']} -> {state['answers'][q['key']]}" for i, q in enumerate(QUESTIONS)]
    lines.append(f"Theme: {state['theme']['name']} ({state['theme']['primary']})")
    lines.append(f"Logo: {state['output_dir']}/logo.svg")
    reply = interrupt({"question": "\n".join(lines) + "\n\nType yes, or: edit 2 / edit theme / edit logo",
                       "options": []}).strip().lower()

    update = {"decision": reply, "editing": False}
    parts = reply.split()
    if len(parts) == 2 and parts[0] == "edit" and parts[1].isdigit():
        n = int(parts[1])
        if 1 <= n <= len(QUESTIONS):
            update.update({"q_index": n - 1, "editing": True})
    return update


def build_requirements_json(state):
    # nothing to compute here yet; the real file is written in phase 6
    return {}


def _retrieve_evidence_for_analysis(state):
    """
    Phase 3C.1: builds a query from the client's own project context and
    retrieves supporting evidence from the (optional, possibly empty or
    unconfigured) persistent knowledge base.

    Deliberately degrades to an empty evidence list — never raises out
    of this function — on ANY failure (missing credentials, store not
    yet ingested, a transient retrieval error): RAG is an enhancement to
    analyse_requirements, not a precondition for it. The underlying
    RetrievalService.retrieve() already returns [] cleanly for an empty
    store; this wrapper additionally catches construction-time failures
    (e.g. GEMINI_API_KEY not set) so the BA elicitation itself is never
    blocked by RAG being unavailable or unconfigured.
    """
    query = f"{state['answers']['description']} Features: {state['answers']['features']}"
    try:
        from services.retrieval_service import RetrievalService
        chunks = RetrievalService().retrieve(query)
        # Converted to plain dicts for consistency with the rest of
        # `state` (which is otherwise all plain JSON-serializable types)
        # rather than carrying dataclass instances through the graph.
        return [
            {"text": c.text, "source": c.source, "chunk_id": c.chunk_id,
             "score": c.score, "metadata": c.metadata}
            for c in chunks
        ]
    except Exception as e:
        print(f"(Retrieval unavailable this run, continuing without it: {e})")
        return []


def _format_evidence_for_prompt(evidence):
    if not evidence:
        return "(no relevant knowledge-base evidence retrieved for this project)"
    lines = []
    for chunk in evidence:
        lines.append(f"- [source: {chunk['source']}, chunk_id: {chunk['chunk_id']}] {chunk['text']}")
    return "\n".join(lines)


def analyse_requirements(state):
    qa = [{"question": q["text"], "answer": state["answers"][q["key"]]} for q in QUESTIONS]
    evidence = _retrieve_evidence_for_analysis(state)
    evidence_block = _format_evidence_for_prompt(evidence)
    analysis = ask_llm_json(
        f"Client questions and answers:\n{json.dumps(qa)}\n"
        f"Problems to fix from last attempt: {state.get('gaps') or 'none'}\n"
        f"RETRIEVED KNOWLEDGE-BASE CONTEXT (demonstration content; may be empty; "
        f"general guidance only, NOT proof that any specific client requirement is "
        f"confirmed):\n{evidence_block}\n"
        "Write a requirement analysis as JSON with keys: objectives (list of strings), "
        "stakeholders (list of strings), "
        "functional_requirements (list of {id:'FR-1', text, feature, "
        "source_refs: optional list of {source, chunk_id} — include ONLY when a "
        "requirement is directly supported by the RETRIEVED KNOWLEDGE-BASE CONTEXT "
        "above; omit source_refs entirely for requirements based on the client's own "
        "answers or your own reasonable assumptions, since those are not "
        "source-supported}), "
        "non_functional_requirements (list of strings), "
        "scope ({in:[], out:[]}), risks (list of strings), data_entities (list of strings). "
        "Every client feature must be covered by at least one functional requirement; "
        "copy that feature's words into the 'feature' field. "
        "Do NOT invent facts the client did not give, and do NOT treat retrieved general "
        "guidance as confirmation of a client-specific requirement."
    )
    return {"analysis": analysis, "retrieved_evidence": evidence}


def generate_user_stories(state):
    stories = ask_llm_json(
        f"Functional requirements:\n{json.dumps(state['analysis']['functional_requirements'])}\n"
        f"Client must-have features: {state['answers']['must_have']}\n"
        f"Problems to fix: {state.get('gaps') or 'none'}\n"
        f"Client feedback: {state.get('feedback') or 'none'}\n"
        "Write user stories as a JSON list of {id:'US-1', as_a, i_want, so_that, "
        "fr_ids:['FR-1'], priority:'Must'|'Should'|'Could'|'Wont'}. "
        "Every functional requirement needs at least one story. "
        "Use priority Must for the client's must-haves."
    )
    return {"stories": stories}


def generate_acceptance_criteria(state):
    criteria = ask_llm_json(
        f"User stories:\n{json.dumps(state['stories'])}\n"
        f"Problems to fix: {state.get('gaps') or 'none'}\n"
        f"Client feedback: {state.get('feedback') or 'none'}\n"
        "For EACH story write 2 to 4 acceptance criteria as a JSON list of "
        "{id:'AC-1', story_id:'US-1', given, when, then}."
    )
    return {"criteria": criteria}


def validate(state):
    frs = state["analysis"]["functional_requirements"]
    features = [f.strip().lower() for f in state["answers"]["features"].split(",") if f.strip()]

    # Three checks. Each one lists what is missing.
    fr_text = " ".join(fr.get("feature", "").lower() for fr in frs)
    covered = {fid for s in state["stories"] for fid in s["fr_ids"]}
    has_criteria = {c["story_id"] for c in state["criteria"]}
    problems = {
        "fr": [f for f in features if f not in fr_text],                       # feature has no FR
        "story": [fr["id"] for fr in frs if fr["id"] not in covered],          # FR has no story
        "criteria": [s["id"] for s in state["stories"] if s["id"] not in has_criteria],
    }
    go_back_to = {"fr": "analyse_requirements", "story": "generate_user_stories",
                  "criteria": "generate_acceptance_criteria"}

    for kind in ["fr", "story", "criteria"]:
        if problems[kind] and state["repairs"][kind] < 2:        # repair at most 2 times
            repairs = {**state["repairs"], kind: state["repairs"][kind] + 1}
            return {"gaps": f"Missing ({kind}): {problems[kind]}",
                    "next_step": go_back_to[kind], "repairs": repairs}

    left = {k: v for k, v in problems.items() if v}
    return {"gaps": "", "leftover": str(left) if left else "", "next_step": "review_stories"}


def review_stories(state):
    lines = []
    for s in state["stories"]:
        lines.append(f"{s['id']} [{s['priority']}] As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}")
        for c in state["criteria"]:
            if c["story_id"] == s["id"]:
                lines.append(f"    Given {c['given']} / When {c['when']} / Then {c['then']}")
    reply = interrupt({"question": "\n".join(lines) +
                       "\n\nType approve, or: change stories: <what> / change criteria: <what>",
                       "options": []}).strip()

    update = {"review": reply.lower(), "feedback": reply}
    if reply.lower().startswith("change"):
        update["repairs"] = {"fr": 0, "story": 0, "criteria": 0}   # fresh repair budget
    return update


def write_requirements_json(state):
    """THE handoff file. The Software Architect agent reads this and nothing else."""
    data = {
        "project": {k: state["answers"][k] for k in ["name", "description", "type"]},
        "qa": [{"question": q["text"], "answer": state["answers"][q["key"]]} for q in QUESTIONS],
        "ui": {"theme": state["theme"], "logo_svg": state["logo"]},
        "analysis": state["analysis"],
        "user_stories": state["stories"],
        "acceptance_criteria": state["criteria"],
        "validation": {"passed": not state.get("leftover"), "remaining_gaps": state.get("leftover", "")},
    }
    path = f"{state['output_dir']}/requirements.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    # Phase 3B.3: also expose the exact dict just written via state, so
    # canonical_validate() (below) can adapt it without re-deriving the
    # same structure from scratch a second time — avoids duplicating
    # this function's own field-assembly logic and the drift risk that
    # would create. This does NOT change what's written to disk: the
    # legacy requirements.json artifact and the handoff comment above
    # are both unchanged.
    return {"files": [path], "legacy_contract": data}


def write_analysis_doc(state):
    a = state["analysis"]
    sections = [
        ("Objectives", a["objectives"]),
        ("Stakeholders", a["stakeholders"]),
        ("Functional requirements", [f"{fr['id']}: {fr['text']}" for fr in a["functional_requirements"]]),
        ("Non-functional requirements", a["non_functional_requirements"]),
        ("Scope (in)", a["scope"]["in"]),
        ("Scope (out)", a["scope"]["out"]),
        ("Risks", a["risks"]),
        ("Data entities", a["data_entities"]),
    ]
    return {"files": [save_doc("requirement_analysis.docx", "Requirement Analysis", sections,
                                output_dir=state["output_dir"])]}


def write_prd(state):
    a = state["analysis"]
    sections = [
        ("Client answers", [f"{q['text']} {state['answers'][q['key']]}" for q in QUESTIONS]),
        ("UI", [f"Theme: {state['theme']['name']}, primary {state['theme']['primary']}"]),
        ("Objectives", a["objectives"]),
        ("Functional requirements", [f"{fr['id']}: {fr['text']}" for fr in a["functional_requirements"]]),
    ]
    title = f"Project Requirements: {state['answers']['name']}"
    return {"files": [save_doc("project_requirements.docx", title, sections,
                                output_dir=state["output_dir"])]}


def write_stories_doc(state):
    sections = []
    for s in state["stories"]:
        lines = [f"As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}."]
        lines += [f"Given {c['given']}, when {c['when']}, then {c['then']}"
                  for c in state["criteria"] if c["story_id"] == s["id"]]
        sections.append((f"{s['id']} ({s['priority']})", lines))
    return {"files": [save_doc("user_stories.docx", "User Stories", sections,
                                output_dir=state["output_dir"])]}


def _canonical_dependencies():
    """
    Lazily imports the adapter and the canonical validator.

    Layout note (Phase 3B.3): `adapter/` and `ba_contract_prototype/`
    live at the repository root as siblings of this application
    directory (Business-Analyst-Agent-main/), the same flat layout
    already established in every earlier phase of this project —
    ba_contract_prototype was never merged into this app, by explicit
    instruction, and the new adapter package follows the same
    convention. That means this app's own sys.path (rooted at
    Business-Analyst-Agent-main/ when run normally) does not include
    them by default; the single sys.path adjustment below adds the
    repository root once, right before these two specific imports are
    needed, rather than globally at module load time.

    Kept as a local import (not a top-of-file import) and isolated in
    this one function so the sys.path change is easy to find, easy to
    remove if this app is ever repackaged as an installable project,
    and has zero effect on any other node in this file.
    """
    import os
    import sys
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from adapter.adapter import adapt, MappingError
    from ba_contract_prototype.validator import validate
    return adapt, MappingError, validate


def canonical_validate(state):
    """
    Phase 3B.3: adapts the legacy contract this run just wrote
    (state["legacy_contract"], set by write_requirements_json above)
    into the canonical ba_contract_prototype schema, and runs the
    existing, UNMODIFIED deterministic validator against it.

    This is strictly additive and non-blocking:
      - It never modifies or re-writes the legacy requirements.json
        artifact, and never touches the existing three-check
        validate()/repair-loop node above.
      - A canonical outcome of "failed", "requires_human_review", or
        even a MappingError does NOT crash the workflow or erase any
        legacy artifact — it is written to its own, separate file and
        returned in state for whatever later stage wants to act on it
        (none does yet; that is explicitly out of scope here).
      - The canonical artifact is written to
        state["output_dir"]/canonical_requirements.json — inside this
        run's own isolated directory, per Phase 3B.2.
    """
    adapt, MappingError, validate_canonical = _canonical_dependencies()
    output_dir = state["output_dir"]
    legacy_contract = state["legacy_contract"]

    try:
        result = adapt(legacy_contract)
    except MappingError as e:
        report = {"canonical_status": "mapping_error", "canonical_error": str(e)}
        with open(f"{output_dir}/canonical_requirements.json", "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nCanonical validation could not run: {e}")
        return {"canonical_status": "mapping_error", "canonical_error": str(e)}

    validation_result = validate_canonical(result.contract)
    report = {
        "canonical_status": validation_result.state,
        "canonical_contract": result.contract,
        "canonical_provenance": result.provenance,
        "canonical_unresolved": [g.__dict__ for g in validation_result.unresolved_markers],
        "canonical_gaps": [g.__dict__ for g in validation_result.gaps],
        # Phase 3C.1: the knowledge-base evidence retrieved for this run's
        # analysis (possibly empty), carried here rather than into the
        # legacy requirements.json or adapter.adapt()'s own contract, so
        # retrieval provenance is preserved without touching either of
        # those already-tested surfaces. Per-FR citations the model made
        # (functional_requirements[*].source_refs, if present) are already
        # preserved separately via the adapter's own legacy FR passthrough.
        "retrieved_evidence": state.get("retrieved_evidence", []),
    }
    with open(f"{output_dir}/canonical_requirements.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nCanonical validation: {validation_result.state}"
          + (f" ({len(validation_result.gaps)} gap(s))" if validation_result.gaps else ""))

    return {
        "canonical_status": validation_result.state,
        "canonical_gaps": report["canonical_gaps"],
    }


def handoff(state):
    print("\nAll deliverables are ready:")
    for f in state["files"]:
        print("  -", f)
    print(f"Handing {state['output_dir']}/requirements.json to the Software Architect agent.")
    return {}
