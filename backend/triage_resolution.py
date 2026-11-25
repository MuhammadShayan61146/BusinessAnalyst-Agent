"""
TriageResolutionService: the "human" half of ambiguity/consistency triage.

When a run finishes, canonical_requirements.json lists the open
`human_flagged_concerns` the triage rules found. A person reviews them and
marks each as reviewed. This service then:

  1. marks ONLY the named concerns as resolved (recording who and when),
  2. re-runs the deterministic canonical validator on the contract,
  3. rewrites canonical_requirements.json with the new status.

The new validation status comes exclusively from the validator, exactly as
before; a person can resolve a concern but cannot set the status directly.
The file path comes from the server (the session's own output folder),
never from the client.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

CANONICAL_FILENAME = "canonical_requirements.json"


class TriageResolutionError(Exception):
    pass


class TriageResolutionService:
    def __init__(self, validate_fn):
        # validate_fn: ba_contract_prototype.validator.validate (injected so this
        # class stays importable and testable without that package on the path).
        self._validate = validate_fn

    def resolve(self, output_dir: str, concern_ids, resolved_by: str) -> dict:
        path = os.path.join(output_dir, CANONICAL_FILENAME)
        if not os.path.isfile(path):
            raise TriageResolutionError("No canonical requirements are available for this session yet.")
        with open(path) as f:
            report = json.load(f)
        contract = report.get("canonical_contract")
        if not isinstance(contract, dict):
            raise TriageResolutionError(
                "This run has no canonical contract to review (status: "
                f"{report.get('canonical_status', 'unknown')}).")

        concerns = contract.get("human_flagged_concerns") or []
        by_id = {c.get("id"): c for c in concerns if isinstance(c, dict)}
        wanted = list(by_id) if concern_ids == "all" else list(concern_ids or [])
        unknown = [cid for cid in wanted if cid not in by_id]
        if unknown:
            raise TriageResolutionError("Unknown concern id(s): " + ", ".join(map(str, unknown)))
        if not wanted:
            raise TriageResolutionError("No concern ids were given.")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for cid in wanted:
            by_id[cid]["resolved"] = True
            by_id[cid]["resolved_by"] = resolved_by
            by_id[cid]["resolved_at"] = now

        result = self._validate(contract)
        report["canonical_status"] = result.state
        report["canonical_gaps"] = [g.__dict__ for g in result.gaps]
        report["canonical_unresolved"] = [g.__dict__ for g in result.unresolved_markers]

        # Atomic rewrite: write a temp file in the same folder, then replace.
        fd, tmp = tempfile.mkstemp(suffix=".json", dir=output_dir)
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, path)

        open_count = sum(1 for c in concerns if not c.get("resolved"))
        return {
            "canonical_status": result.state,
            "canonical_gaps": report["canonical_gaps"],
            "canonical_concerns": concerns,
            "open_concerns": open_count,
        }
