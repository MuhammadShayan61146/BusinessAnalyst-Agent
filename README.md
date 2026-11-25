# Business Analyst Agent

A RAG-backed Business Analyst Agent built on LangGraph. It interviews a
client about a software idea and produces structured, traceable requirements, user
stories, acceptance criteria and documents. A web frontend and FastAPI backend sit on top
of the same agent that the command-line interface uses.

## Features

- **Guided interview** (11 questions, including business case and task breakdown), theme and logo selection.
- **OpenRouter** as the model.
- **RAG** over a persistent Chroma knowledge base, with source references on retrieved evidence.
- **Deterministic validation and bounded repair**, then **human review**.
- **Ambiguity and consistency triage**: rule-based checks flag vague wording, duplicates and scope
  conflicts; a person reviews them and the validator recomputes the status.
- **Canonical requirements contract** validated by a deterministic validator that alone decides the status.
- **Accounts and history**: sign-in, per-user session history, sessions survive a server restart.
- **Knowledge-base upload** for administrators.
- **Per-run artifact folders**, downloadable only by the session's owner.

## Project layout

```
.
├── Business-Analyst-Agent-main/   the agent: LangGraph workflow, Gemini provider, RAG services,
│                                   triage rules, knowledge base, scripts, CLI (main.py)
├── backend/                        FastAPI API: auth, sessions, artifacts, triage, knowledge upload
├── frontend/                       browser UI (HTML/CSS/JavaScript, no build step)
├── adapter/                        agent output -> canonical contract
├── ba_contract_prototype/          canonical schema + deterministic validator
└── tests_main_app/                 regression tests for the agent
```


## Installation

Requires Python 3.10+ and a OpenRouter API key.

```bash
cd Business-Analyst-Agent-main
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running

### 1. (Optional) index the knowledge base
```bash
cd Business-Analyst-Agent-main
python3 scripts/ingest_knowledge_base.py
```

### 2. Create an administrator (only administrators can upload to the knowledge base)
```bash
cd Business-Analyst-Agent-main
python3 scripts/create_user.py --admin admin
```
Ordinary users can register themselves from the sign-in page. Names listed in `ADMIN_USERNAMES`
cannot be self-registered.

### 3. Start the backend 
```bash
uvicorn backend.app:app --reload --port 8000
```
Open http://localhost:8000. The backend also serves the frontend.

### 4. Command-line interface 
```bash
cd Business-Analyst-Agent-main
python3 main.py
```

## Using the web application

1. Create an account (or sign in), then **Start new session**.
2. Answer the questions. Closed questions offer buttons.
3. Pick one of the three **logo previews**; check the **structured summary** and confirm.
4. At the **review** step, items flagged by the triage rules are listed before you approve.
5. On the results page you see the requirements, the **user stories with their acceptance criteria and
   the requirements they implement**, the validation status and the downloadable files.
6. Flagged items can be marked **reviewed**; the status is then recomputed by the validator.
7. **My sessions** lists your previous sessions. Administrators also get a **Knowledge base** page.


## Security design

- Passwords are stored as salted PBKDF2-SHA256 hashes; login tokens are stored hashed and expire.
- Repeated failed logins are throttled.
- Clients never send file paths. Downloads use opaque artifact ids that the server matches against
  the session's own folder. Uploaded filenames are reduced to a safe name inside `knowledge_base/uploads/`.
- Uploads are test-read first, size-limited, and rolled back if indexing fails.
- Model-generated logos are shown only through `<img>` (scripts cannot run), and all text is inserted
  with `textContent`.
- Secrets live in `.env`, which is git-ignored.

