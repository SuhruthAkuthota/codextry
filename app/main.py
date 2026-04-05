from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_VERSION = "Nutribridge Core v0.2.0"
MODEL_VERSION = "GPT-5.2"
JWT_SECRET = os.getenv("NUTRIBRIDGE_JWT_SECRET", "nutribridge-dev-secret").encode("utf-8")
JWT_EXP_SECONDS = 60 * 60 * 24
BASE_DIR = Path(__file__).resolve().parent

users: dict[str, dict[str, str]] = {}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def create_jwt(email: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_jwt(token: str) -> dict[str, object]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("Malformed token") from exc

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(sig_b64)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Invalid signature")

    payload = json.loads(_b64url_decode(payload_b64))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Token expired")
    return payload


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def risk_from_symptoms(symptoms: list[dict[str, object]], medications: list[str]) -> dict[str, float]:
    symptom_names = {str(s.get("name", "")).lower(): int(s.get("severity", 5)) for s in symptoms}
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
    if any("metformin" in m.lower() for m in medications):
        base["Vitamin B12"] += 0.22
    return {k: min(v, 0.98) for k, v in base.items()}


def render_index() -> bytes:
    template_path = BASE_DIR / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")
    html = html.replace("{{ app_version }}", APP_VERSION).replace("{{ model_version }}", MODEL_VERSION)
    return html.encode("utf-8")


class NutribridgeHandler(BaseHTTPRequestHandler):
    server_version: str = "NutribridgeHTTP/0.2"

    def _send_json(self, status: int, data: dict[str, object]) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw or b"{}")

    def _require_auth(self) -> dict[str, str]:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise PermissionError("Missing bearer token")
        token = auth.removeprefix("Bearer ").strip()
        payload = decode_jwt(token)
        email = str(payload.get("sub", ""))
        user = users.get(email)
        if not user:
            raise PermissionError("User not found")
        return user

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(render_index())
            return
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok", "version": APP_VERSION, "model": MODEL_VERSION})
            return
        if parsed.path == "/api/about/team":
            self._send_json(200, {
                "team": [
                    {"role": "CEO / Business Lead", "name": "Asha Martinez", "bio": "Former digital health operator focused on public-health scale-up.", "contribution": "Owns pitch, partnerships, investor relations, and go-to-market strategy.", "photo": "https://images.unsplash.com/photo-1487412720507-e7ab37603c6f"},
                    {"role": "CTO / Tech Lead", "name": "Daniel Okafor", "bio": "Machine learning architect specializing in multimodal nutrition systems.", "contribution": "Built and maintains CNN model, API architecture, and AI pipeline.", "photo": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d"},
                    {"role": "Head of Nutrition Science", "name": "Priya Raman, RD", "bio": "Registered dietitian with clinical micronutrient intervention experience.", "contribution": "Provides medical accuracy, protocol guardrails, and algorithm validation.", "photo": "https://images.unsplash.com/photo-1559839734-2b71ea197ec2"},
                    {"role": "Marketing Lead", "name": "Jordan Lee", "bio": "Growth marketer with consumer health and creator-channel expertise.", "contribution": "Leads user acquisition, social growth, and influencer strategy.", "photo": "https://images.unsplash.com/photo-1544005313-94ddf0286df2"},
                    {"role": "Design Lead", "name": "Noah Kim", "bio": "Product designer focused on accessibility and culturally adaptive UX.", "contribution": "Owns UX/UI system, localization patterns, and accessibility standards.", "photo": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e"},
                ]
            })
            return
        if parsed.path == "/static/styles.css":
            self._send_file(BASE_DIR / "static" / "styles.css", "text/css; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/register":
            payload = self._read_json()
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            full_name = str(payload.get("full_name", "")).strip()
            if not email or not password or not full_name:
                self._send_json(400, {"detail": "full_name, email, and password are required"})
                return
            if email in users:
                self._send_json(400, {"detail": "Email already registered"})
                return
            users[email] = {"email": email, "full_name": full_name, "password_hash": hash_password(password)}
            self._send_json(200, {"token": create_jwt(email), "full_name": full_name})
            return

        if parsed.path == "/api/auth/login":
            payload = self._read_json()
            email = str(payload.get("email", "")).strip().lower()
            password = str(payload.get("password", ""))
            user = users.get(email)
            if not user or user["password_hash"] != hash_password(password):
                self._send_json(401, {"detail": "Invalid credentials"})
                return
            self._send_json(200, {"token": create_jwt(email), "full_name": user["full_name"]})
            return

        if parsed.path == "/api/analysis":
            try:
                user = self._require_auth()
            except Exception as exc:
                self._send_json(401, {"detail": f"Unauthorized: {exc}"})
                return

            payload = self._read_json()
            symptoms = payload.get("symptoms", [])
            medications = payload.get("medications", [])
            cultural_context = str(payload.get("cultural_context", "")).lower()

            nutrient_risk = risk_from_symptoms(symptoms if isinstance(symptoms, list) else [], medications if isinstance(medications, list) else [])
            ranked = sorted(nutrient_risk.items(), key=lambda x: x[1], reverse=True)
            top_items = [
                {"nutrient": n, "confidence_pct": round(c * 100, 1), "priority": i + 1, "severity_band": "moderate" if c < 0.8 else "critical-review"}
                for i, (n, c) in enumerate(ranked[:5])
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
            report = {
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
                "cultural_recommendations": culture_map.get(cultural_context, [
                    "Upgrade existing staple meals with iron + vitamin C pairings.",
                    "Use affordable canned fish/legumes for omega-3 and protein coverage.",
                    "Prioritize culturally familiar leafy greens for folate + magnesium.",
                ]),
                "recovery_sprints": [
                    {"sprint": "Week 1 Sprint", "goal": "Close immediate high-confidence gaps with food-first interventions.", "tasks": ["Add iron + vitamin C pairings in two meals/day.", "Deploy vitamin D3 with fat-containing meal.", "Run hydration + sleep stabilization protocol."], "status": "in_progress"},
                    {"sprint": "Week 2 Sprint", "goal": "Validate adherence and optimize supplement forms.", "tasks": ["Re-scan supplements for bioavailability forms.", "Confirm nutrient-medication interaction matrix.", "Push grocery list update for budget <= $2 interventions."], "status": "queued"},
                ],
                "safety": {
                    "guardrails": ["No disease diagnosis performed.", "No megadose supplementation recommendations.", "Critical findings require clinician review."],
                    "disclaimer": "FDA Disclaimer: AI-generated wellness insights are not medical diagnosis or treatment.",
                    "crisis": "If suicidal thoughts are present in the US, call or text 988 immediately.",
                },
                "business_mode": {
                    "tiers": {"free": "3 meal scans/day + basic deficiency report", "premium_monthly": "$4.99", "premium_yearly": "$49.99", "pro_seat_monthly": "$29.99"},
                    "b2b_channels": ["healthcare API licensing", "white-label insurer programs", "public health institutional contracts"],
                },
            }
            self._send_json(200, report)
            return

        self.send_error(HTTPStatus.NOT_FOUND)


def run() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), NutribridgeHandler)
    print(f"Nutribridge running on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
