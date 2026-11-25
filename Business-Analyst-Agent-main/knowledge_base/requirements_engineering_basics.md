

## Writing good requirements

- A functional requirement describes one observable behaviour of the system and
  is phrased so a tester can check it ("The system shall email a PDF report to
  every subscriber at 08:00 on the first day of each month").
- Avoid vague words such as "fast", "easy", "intuitive", "flexible" or "etc.".
  Replace each with a measurable target or an explicit list.
- Each requirement should have a unique, stable identifier and be traceable to a
  business objective, and forward to a user story and acceptance criteria.
- Keep one requirement per statement; "and" often signals two requirements.
- Record assumptions and open questions separately from confirmed requirements.

## User stories and acceptance criteria

- A user story names a role, a goal and a reason: "As a data analyst, I want to
  save a dashboard so that I can reopen it later."
- Acceptance criteria use Given / When / Then and describe observable results,
  including at least one failure or edge case per story.
- A story with no acceptance criteria cannot be verified and should not be
  accepted into a release.

## Scope management

- State explicitly what is out of scope; unlisted work is a common source of
  disagreement later.
- A feature cannot be both in scope and out of scope; review contradictions
  with the client before design starts.
- Mark must-have features for the first release separately from nice-to-have
  features.
