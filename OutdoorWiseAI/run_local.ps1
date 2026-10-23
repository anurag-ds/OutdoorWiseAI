# Run from the project folder in PowerShell:  .\run_local.ps1
# 1) put your own email here (Nominatim policy requires an identifying contact)
$env:CONTACT_EMAIL = "you@example.com"
# 2) none = template answers (no model needed). Use "transformers" only on Python 3.11/3.12 with torch installed.
$env:LLM_BACKEND = "none"
python -m uvicorn app.main:app --port 7860
