# Nutribridge

Nutribridge is a dark-theme clinical wellness website prototype that detects likely micronutrient deficiencies using a structured AI-style analysis pipeline.

## Highlights
- JWT-style authentication (`/api/auth/register`, `/api/auth/login`) implemented with HMAC-SHA256 tokens
- Deficiency analysis endpoint (`/api/analysis`) with confidence scores and sprint-based recovery plans
- Software-engineer persona output style with versioned pipeline/report schema
- Team page endpoint with clearly defined roles and one-line bios (`/api/about/team`)
- Safety guardrails and FDA disclaimer in every analysis report
- Business model references (freemium, B2B licensing, institutional channels)
- Runs without installing third-party packages

## Run locally
```bash
python3 app/main.py
```

Open http://127.0.0.1:8000

## Important medical notice
This project provides AI-generated wellness insights and is **not** a medical diagnosis tool.
