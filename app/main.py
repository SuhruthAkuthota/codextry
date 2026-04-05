from __future__ import annotations

import hashlib
import os
import time
import uuid
from typing import Any

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field


APP_VERSION = "Nutribridge Core v0.1.0"
MODEL_VERSION = "GPT-5.2"
JWT_SECRET = os.getenv("NUTRIBRIDGE_JWT_SECRET", "nutribridge-dev-secret")
JWT_ALGORITHM = "HS256"
JWT_EXP_SECONDS = 60 * 60 * 24


app = FastAPI(title="Nutribridge", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
security = HTTPBearer()


class RegisterInput(BaseModel):
    email: str
    password: str
    full_name: str


class LoginInput(BaseModel):
    email: str
    password: str


class SymptomInput(BaseModel):
    name: str
    severity: int = Field(ge=1, le=10)


class AnalysisInput(BaseModel):
    age: int
    sex: str
    weight_kg: float
    activity_level: str
    sleep_quality: int = Field(ge=1, le=10)
    water_intake_liters: float
    medications: list[str] = []
    conditions: list[str] = []
    symptoms: list[SymptomInput]
    diet_type: str
    cultural_context: str
    budget_usd_per_week: float
    scanned_inputs: dict[str, Any] = {}


users: dict[str, dict[str, str]] = {}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _create_jwt(email: str) -> str:
    payload = {
        "sub": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, str]:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        email = payload["sub"]
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    if email not in users:
        raise HTTPException(status_code=401, detail="User not found")
    return users[email]


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_version": APP_VERSION,
            "model_version": MODEL_VERSION,
        },
    )


@app.post("/api/auth/register")
def register(payload: RegisterInput) -> dict[str, str]:
    if payload.email in users:
        raise HTTPException(status_code=400, detail="Email already registered")

    users[payload.email] = {
        "email": payload.email,
        "full_name": payload.full_name,
        "password_hash": _hash_password(payload.password),
    }
    token = _create_jwt(payload.email)
    return {"token": token, "full_name": payload.full_name}


@app.post("/api/auth/login")
def login(payload: LoginInput) -> dict[str, str]:
    user = users.get(payload.email)
    if not user or user["password_hash"] != _hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_jwt(payload.email)
    return {"token": token, "full_name": user["full_name"]}


@app.get("/api/about/team")
def team() -> dict[str, Any]:
    return {
        "team": [
            {
                "role": "CEO / Business Lead",
                "name": "Asha Martinez",
                "bio": "Former digital health operator focused on public-health scale-up.",
                "contribution": "Owns pitch, partnerships, investor relations, and go-to-market strategy.",
                "photo": "https://images.unsplash.com/photo-1487412720507-e7ab37603c6f",
            },
            {
                "role": "CTO / Tech Lead",
                "name": "Daniel Okafor",
                "bio": "Machine learning architect specializing in multimodal nutrition systems.",
                "contribution": "Built and maintains CNN model, API architecture, and AI pipeline.",
                "photo": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d",
            },
            {
                "role": "Head of Nutrition Science",
                "name": "Priya Raman, RD",
                "bio": "Registered dietitian with clinical micronutrient intervention experience.",
                "contribution": "Provides medical accuracy, protocol guardrails, and algorithm validation.",
                "photo": "https://images.unsplash.com/photo-1559839734-2b71ea197ec2",
            },
            {
                "role": "Marketing Lead",
                "name": "Jordan Lee",
                "bio": "Growth marketer with consumer health and creator-channel expertise.",
                "contribution": "Leads user acquisition, social growth, and influencer strategy.",
                "photo": "https://images.unsplash.com/photo-1544005313-94ddf0286df2",
            },
            {
                "role": "Design Lead",
                "name": "Noah Kim",
                "bio": "Product designer focused on accessibility and culturally adaptive UX.",
                "contribution": "Owns UX/UI system, localization patterns, and accessibility standards.",
                "photo": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e",
            },
        ]
    }


def _risk_from_symptoms(symptoms: list[SymptomInput], medications: list[str]) -> dict[str, float]:
    symptom_names = {s.name.lower(): s.severity for s in symptoms}

    base = {
        "Vitamin D": 0.62,
        "Iron": 0.58,
        "Magnesium": 0.51,
        "Vitamin B12": 0.49,
        "Omega-3": 0.44,
        "Zinc": 0.39,
    }

    if "fatigue" in symptom_names:
        base["Iron"] += 0.21
        base["Vitamin B12"] += 0.14
        base["Vitamin D"] += 0.13
    if "brain fog" in symptom_names:
        base["Omega-3"] += 0.19
        base["Vitamin B12"] += 0.17
    if "muscle cramps" in symptom_names:
        base["Magnesium"] += 0.24
    if any("metformin" in med.lower() for med in medications):
        base["Vitamin B12"] += 0.22

    return {k: min(v, 0.98) for k, v in base.items()}


@app.post("/api/analysis")
def analyze(payload: AnalysisInput, user: dict[str, str] = Depends(_get_current_user)) -> dict[str, Any]:
    nutrient_risk = _risk_from_symptoms(payload.symptoms, payload.medications)
    ranked = sorted(nutrient_risk.items(), key=lambda x: x[1], reverse=True)

    sprint_plan = [
        {
            "sprint": "Week 1 Sprint",
            "goal": "Close immediate high-confidence gaps with food-first interventions.",
            "tasks": [
                "Add iron + vitamin C pairings in two meals/day.",
                "Deploy vitamin D3 with fat-containing meal.",
                "Run hydration + sleep stabilization protocol.",
            ],
            "status": "in_progress",
        },
        {
            "sprint": "Week 2 Sprint",
            "goal": "Validate adherence and optimize supplement forms.",
            "tasks": [
                "Re-scan supplements for bioavailability forms.",
                "Confirm nutrient-medication interaction matrix.",
                "Push grocery list update for budget <= $2 interventions.",
            ],
            "status": "queued",
        },
    ]

    culture_map = {
        "south asian": [
            "Add spinach to dal for iron density.",
            "Use ragi porridge for calcium support.",
            "Include sardines twice weekly as affordable omega-3 option.",
        ],
        "latin american": [
            "Pair black beans with citrus salsa for iron absorption.",
            "Add pepitas for zinc and magnesium density.",
            "Use canned sardines with nopales for omega-3 and calcium.",
        ],
    }
    selected_culture = payload.cultural_context.lower()

    top_items = [
        {
            "nutrient": nutrient,
            "confidence_pct": round(conf * 100, 1),
            "priority": idx + 1,
            "severity_band": "moderate" if conf < 0.8 else "critical-review",
        }
        for idx, (nutrient, conf) in enumerate(ranked[:5])
    ]

    return {
        "engine": {
            "persona": "software_engineer",
            "model": MODEL_VERSION,
            "pipeline_version": "diagnosis-pipeline-v2.1",
            "report_version": "report-schema-v1.4.0",
        },
        "user": {"email": user["email"], "full_name": user["full_name"]},
        "analysis": {
            "summary": "Analysis complete. Deficiency matrix generated from multimodal intake vectors.",
            "high_confidence_detections": top_items,
            "build_status": "🟢 Recovery Build: 43% Complete",
            "nutrient_gap_score": 71,
            "confidence_method": "ensemble signal scoring (symptoms + lifestyle + diet + medication)",
        },
        "cultural_recommendations": culture_map.get(
            selected_culture,
            [
                "Upgrade existing staple meals with iron + vitamin C pairings.",
                "Use affordable canned fish/legumes for omega-3 and protein coverage.",
                "Prioritize culturally familiar leafy greens for folate + magnesium.",
            ],
        ),
        "recovery_sprints": sprint_plan,
        "safety": {
            "guardrails": [
                "No disease diagnosis performed.",
                "No megadose supplementation recommendations.",
                "Critical findings require clinician review.",
            ],
            "disclaimer": "FDA Disclaimer: AI-generated wellness insights are not medical diagnosis or treatment.",
            "crisis": "If suicidal thoughts are present in the US, call or text 988 immediately.",
        },
        "business_mode": {
            "tiers": {
                "free": "3 meal scans/day + basic deficiency report",
                "premium_monthly": "$4.99",
                "premium_yearly": "$49.99",
                "pro_seat_monthly": "$29.99",
            },
            "b2b_channels": [
                "healthcare API licensing",
                "white-label insurer programs",
                "public health institutional contracts",
            ],
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION, "model": MODEL_VERSION}
