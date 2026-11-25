
from __future__ import annotations

import math
import re

# term (regex fragment) -> short hint shown to the reviewer
VAGUE_TERMS = {
    r"fast(?:er|est)?": "give a response-time or throughput target",
    r"quick(?:ly)?": "give a response-time target",
    r"easy|easily": "describe what the user must be able to do, and in how many steps",
    r"user[- ]friendly": "replace with a measurable usability criterion",
    r"intuitive(?:ly)?": "replace with a measurable usability criterion",
    r"simple|simply": "say what is simple, for whom",
    r"scalab\w*": "state the load the system must handle (users, requests, data size)",
    r"flexib\w*": "state which changes it must accommodate",
    r"robust\w*": "state which failures it must tolerate",
    r"secur\w*": "name the security controls or standard required",
    r"efficien\w*": "give a resource or time target",
    r"reliab\w*": "give an availability or error-rate target",
    r"modern": "name the specific technology or behaviour expected",
    r"seamless(?:ly)?": "describe the exact interaction expected",
    r"appropriate(?:ly)?": "state the criterion for 'appropriate'",
    r"adequate(?:ly)?": "state the criterion for 'adequate'",
    r"sufficient(?:ly)?": "state the criterion for 'sufficient'",
    r"as needed|if necessary|as required": "say who decides and when",
    r"etc\.?|and so on|and more": "list the remaining items explicitly",
    r"and/or": "state which of the options applies",
    r"tbd|to be determined": "replace with a decision or record it as an open question",
    r"as soon as possible|asap": "give a deadline",
    r"high[- ]performance": "give a performance target",
    r"minimal|minimum": "give the actual limit",
    r"good|better|best": "state the criterion for 'good'",
}
_VAGUE_RES = [(re.compile(r"\b(?:%s)\b" % pat, re.IGNORECASE), hint, pat)
              for pat, hint in VAGUE_TERMS.items()]

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "with", "in", "on", "by", "at", "as",
    "is", "are", "be", "should", "shall", "must", "will", "can", "that", "this", "it", "its",
    "from", "into", "via", "any", "all", "not", "non", "their", "they", "using", "use",
}
MODALS = {"shall", "should", "must", "will", "can", "allow", "allows", "enable", "enables",
          "support", "supports", "provide", "provides", "let", "lets"}


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", (text or "").lower())
    out = set()
    for w in words:
        if w in STOPWORDS or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def _vague_hits(text: str) -> list:
    hits = []
    for rx, hint, _pat in _VAGUE_RES:
        for m in rx.finditer(text or ""):
            term = m.group(0).strip()
            if term.lower() not in [h[0].lower() for h in hits]:
                hits.append((term, hint))
    return hits


class _Collector:
    def __init__(self):
        self.items = []

    def add(self, *, category, type_, severity, kind, target_ids, description,
            suggestion, term=None, position=None):
        self.items.append({
            "category": category, "type": type_, "severity": severity,
            "target_kind": kind, "target_ids": list(target_ids),
            "description": description, "suggestion": suggestion,
            "term": term, "position": position,
        })


def analyze(analysis: dict, stories: list = None, criteria: list = None) -> list:
    """
    Returns a list of finding dicts (each with a stable sequential id
    "TRI-001", "TRI-002", ...). `analysis`, `stories`, `criteria` use the
    agent's own shapes (FR ids like "FR-1"; NFRs are plain strings and
    are referenced as NFR-001, NFR-002, ... by position).
    """
    analysis = analysis or {}
    stories = stories or []
    criteria = criteria or []
    c = _Collector()

    frs = [fr for fr in analysis.get("functional_requirements", []) if isinstance(fr, dict)]
    nfrs = [n for n in analysis.get("non_functional_requirements", []) if isinstance(n, str)]

    # --- vague wording: functional requirements -------------------------------
    for fr in frs:
        hits = _vague_hits(fr.get("text", ""))
        if hits:
            c.add(category="vague_wording", type_="ambiguity", severity="warning",
                  kind="functional_requirement", target_ids=[fr.get("id", "")],
                  term=", ".join(h[0] for h in hits),
                  description=f"{fr.get('id')} uses vague wording: " + ", ".join(f"'{h[0]}'" for h in hits) + ".",
                  suggestion="; ".join(sorted({h[1] for h in hits})) + ".")

    # --- vague / unmeasurable wording: non-functional requirements ---------------
    for i, text in enumerate(nfrs, start=1):
        nid = f"NFR-{i:03d}"
        hits = _vague_hits(text)
        if hits:
            c.add(category="vague_wording", type_="ambiguity", severity="warning",
                  kind="non_functional_requirement", target_ids=[nid],
                  term=", ".join(h[0] for h in hits),
                  description=f"{nid} uses vague wording: " + ", ".join(f"'{h[0]}'" for h in hits) + ".",
                  suggestion="; ".join(sorted({h[1] for h in hits})) + ".")
        elif not re.search(r"\d", text):
            c.add(category="unmeasurable", type_="ambiguity", severity="info",
                  kind="non_functional_requirement", target_ids=[nid],
                  description=f"{nid} has no measurable target (no number or unit).",
                  suggestion="Add a threshold a tester could check (e.g. a time, count or percentage).")

    # --- not testable: bare noun-phrase functional requirements ---------------------
    for fr in frs:
        words = re.findall(r"[A-Za-z]+", fr.get("text", ""))
        if len(words) < 6 and not (MODALS & {w.lower() for w in words}):
            c.add(category="not_testable", type_="ambiguity", severity="info",
                  kind="functional_requirement", target_ids=[fr.get("id", "")],
                  description=f"{fr.get('id')} is a short noun phrase rather than a testable statement.",
                  suggestion="Rewrite as 'The system shall ...' with the expected behaviour.")

    # --- vague wording: user stories and acceptance criteria -----------------------
    for s in stories:
        if not isinstance(s, dict):
            continue
        hits = _vague_hits(f"{s.get('i_want', '')} {s.get('so_that', '')}")
        if hits:
            c.add(category="vague_wording", type_="ambiguity", severity="warning",
                  kind="user_story", target_ids=[s.get("id", "")],
                  term=", ".join(h[0] for h in hits),
                  description=f"{s.get('id')} uses vague wording: " + ", ".join(f"'{h[0]}'" for h in hits) + ".",
                  suggestion="; ".join(sorted({h[1] for h in hits})) + ".")
    seen_in_story = {}
    for crit in criteria:
        if not isinstance(crit, dict):
            continue
        sid = crit.get("story_id", "")
        seen_in_story[sid] = seen_in_story.get(sid, 0) + 1
        hits = _vague_hits(f"{crit.get('given', '')} {crit.get('when', '')} {crit.get('then', '')}")
        if hits:
            c.add(category="vague_wording", type_="ambiguity", severity="warning",
                  kind="acceptance_criterion", target_ids=[sid], position=seen_in_story[sid],
                  term=", ".join(h[0] for h in hits),
                  description=(f"Acceptance criterion #{seen_in_story[sid]} of {sid} uses vague wording: "
                               + ", ".join(f"'{h[0]}'" for h in hits) + "."),
                  suggestion="; ".join(sorted({h[1] for h in hits})) + ".")

    # --- duplicates -----------------------------------------------------------------
    toks = [(fr.get("id", ""), _tokens(fr.get("text", ""))) for fr in frs]
    for a in range(len(toks)):
        for b in range(a + 1, len(toks)):
            ta, tb = toks[a][1], toks[b][1]
            if len(ta) >= 3 and len(tb) >= 3:
                jac = len(ta & tb) / len(ta | tb)
                if jac >= 0.8:
                    c.add(category="duplicate", type_="ambiguity", severity="warning",
                          kind="functional_requirement", target_ids=[toks[a][0], toks[b][0]],
                          description=f"{toks[a][0]} and {toks[b][0]} look like duplicates (word overlap {jac:.0%}).",
                          suggestion="Merge them, or make the difference between them explicit.")

    # --- scope conflicts --------------------------------------------------------------
    scope = analysis.get("scope") if isinstance(analysis.get("scope"), dict) else {}
    scope_in = [s for s in scope.get("in", []) if isinstance(s, str)]
    scope_out = [s for s in scope.get("out", []) if isinstance(s, str)]
    for i_item in scope_in:
        ti = _tokens(i_item)
        for o_item in scope_out:
            to = _tokens(o_item)
            if ti and to and (ti == to or (min(len(ti), len(to)) >= 2 and (ti <= to or to <= ti))):
                c.add(category="scope_conflict", type_="potential_contradiction", severity="warning",
                      kind="scope", target_ids=[],
                      description=f"'{i_item}' is listed as in scope but '{o_item}' is listed as out of scope.",
                      suggestion="Decide which list the item belongs to.")
    for fr in frs:
        tf = _tokens(fr.get("text", ""))
        for o_item in scope_out:
            to = _tokens(o_item)
            if len(to) >= 2:
                overlap = tf & to
                if len(overlap) >= max(2, math.ceil(0.6 * len(to))):
                    c.add(category="scope_conflict", type_="potential_contradiction", severity="warning",
                          kind="functional_requirement", target_ids=[fr.get("id", "")],
                          description=(f"{fr.get('id')} overlaps the out-of-scope item '{o_item}' "
                                       f"(shared words: {', '.join(sorted(overlap))})."),
                          suggestion="Confirm the requirement is really in scope, or remove it from the out-of-scope list.")

    for n, item in enumerate(c.items, start=1):
        item["id"] = f"TRI-{n:03d}"
    return c.items


def findings_to_concerns(findings: list, fr_id_map: dict, us_id_map: dict, ac_provenance: list) -> list:
    """
    Converts WARNING findings into canonical `human_flagged_concerns`
    entries (shape required by ba_contract_prototype's validator), with
    legacy ids translated to canonical ids. Info findings are not
    converted: they are advice, not blockers.
    """
    ac_lookup = {(p["legacy_story_id"], p["position_within_story"]): p["canonical_id"]
                 for p in (ac_provenance or [])}
    concerns = []
    for f in findings:
        if f["severity"] != "warning":
            continue
        related = []
        for tid in f["target_ids"]:
            if f["target_kind"] == "functional_requirement":
                related.append(fr_id_map.get(tid, tid))
            elif f["target_kind"] == "user_story":
                related.append(us_id_map.get(tid, tid))
            elif f["target_kind"] == "acceptance_criterion":
                related.append(ac_lookup.get((tid, f.get("position")), us_id_map.get(tid, tid)))
            else:
                related.append(tid)
        concerns.append({
            "id": f["id"], "type": f["type"], "description": f["description"],
            "related_ids": related, "resolved": False,
            "category": f["category"], "severity": f["severity"], "suggestion": f["suggestion"],
        })
    return concerns
