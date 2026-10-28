QUESTIONS = [
    {"key": "name", "text": "What is the name of your project?", "options": []},
    {"key": "description", "text": "Describe the project and what it should do.", "options": []},
    {"key": "type", "text": "What type of website is it?",
     "options": ["Online store", "Blog", "Portfolio", "Business site", "Other"]},
    {"key": "users", "text": "Who will use it? (e.g. customers, admin)", "options": []},
    {"key": "features", "text": "List the main features you need (comma separated).", "options": []},
    {"key": "must_have", "text": "Which of those features are must-have for the first launch?", "options": []},
    {"key": "integrations", "text": "Any outside services needed? (payments, email, maps...)",
     "options": [], "optional": True},
    {"key": "tech", "text": "Any technology or framework preference? (e.g. Django)",
     "options": [], "optional": True},
    {"key": "budget_deadline", "text": "Any budget or deadline limits?", "options": [], "optional": True},
]
SKIP_WORDS = {"skip", "none", "no", "n/a", "nothing"}
PRESETS = {
    "Ocean Blue": {"primary": "#1E6FD9", "background": "#F5F9FF"},
    "Forest Green": {"primary": "#2E7D32", "background": "#F4FAF4"},
    "Sunset Orange": {"primary": "#E65100", "background": "#FFF8F3"},
    "Royal Purple": {"primary": "#6A1B9A", "background": "#FAF5FC"},
    "Slate Dark": {"primary": "#90A4AE", "background": "#1E272C"},
}
LOGO_STYLES = ["Minimal", "Playful", "Corporate", "Abstract"]

WRITERS = ["write_requirements_json", "write_analysis_doc", "write_prd", "write_stories_doc"]
