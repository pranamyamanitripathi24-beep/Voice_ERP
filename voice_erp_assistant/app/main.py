"""
FastAPI server — the "API Gateway" front door of the whole system
(slide 3 / slide 7 "Backend: Python (FastAPI)").

Endpoints:
  GET  /               — the website (static/index.html), see static/app.js
                          for how it calls the endpoints below
  POST /voice/text     — text-in/text-out, for demoing without a mic (and
                          for automated tests / any frontend)
  POST /voice/audio     — full pipeline: upload audio -> STT -> NLU ->
                          Dialog Manager -> ERP -> TTS (returns a .wav)
  GET  /health          — liveness check

Run with:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/ in a browser for the website, or
http://127.0.0.1:8000/docs for the raw API (Swagger UI).
"""

import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Header, Cookie, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import database
from app import auth
from app.dialog_manager import handle_utterance

STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="AI Voice-Controlled ERP Assistant")

# Serves style.css and app.js. Mounted under /static so it doesn't shadow
# the /voice/... and /health API routes defined below.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_website():
    """The website itself — same origin as the API, so the browser's
    fetch() calls in static/app.js need no CORS configuration at all."""
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def startup():
    database.init_db(seed=True)


class TextRequest(BaseModel):
    session_id: str
    text: str
    employee_id: str | None = None


class TextResponse(BaseModel):
    reply: str
    awaiting_confirmation: bool
    awaiting_clarification: bool
    result: dict | None = None


class LoginRequest(BaseModel):
    employee_id: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status():
    return {"enabled": auth.auth_enabled(), "demo_enabled": auth.demo_enabled()}


def set_session_cookie(response: Response, token: str):
    secure_cookie = os.environ.get("ERP_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    response.set_cookie(
        "erp_session", token, httponly=True, secure=secure_cookie,
        samesite="strict", max_age=8 * 60 * 60, path="/",
    )


@app.post("/auth/login")
def auth_login(req: LoginRequest, response: Response):
    token, employee = auth.login(req.employee_id, req.password)
    set_session_cookie(response, token)
    return {"employee": employee}


@app.post("/auth/demo")
def auth_demo(response: Response):
    set_session_cookie(response, auth.create_demo_session())
    return {"mode": "demo"}


@app.get("/auth/me")
def auth_me(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    return {"employee": auth.resolve_user(authorization, session_cookie=session_cookie)}


@app.post("/auth/logout")
def auth_logout(
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    auth.revoke(authorization, session_cookie)
    response.delete_cookie("erp_session", path="/", httponly=True, samesite="strict")
    return {"ok": True}


@app.get("/erp/options")
def erp_options(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    """Provides display-safe employees, products, and sales periods to the UI."""
    user = auth.resolve_user(authorization, session_cookie=session_cookie)
    options = database.get_context_options()
    if user["role"] == "field_worker":
        options["employees"] = [
            employee for employee in options["employees"]
            if employee["employee_id"] == user["employee_id"]
        ]
    return options


@app.get("/erp/inventory")
def erp_inventory(
    search: str = "",
    low_stock_only: bool = False,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    auth.resolve_user(authorization, session_cookie=session_cookie)
    return {"items": database.get_inventory(search, low_stock_only)}


@app.get("/dashboard/summary")
def dashboard_summary(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    user = auth.resolve_user(authorization, session_cookie=session_cookie)
    return database.get_dashboard_summary(
        employee_id=user.get("employee_id"),
        include_sales=user["role"] in {"finance", "admin"},
    )


@app.get("/reports/sales")
def download_sales_report(
    period: str = "this_month",
    format: str = "csv",
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    user = auth.resolve_user(authorization, session_cookie=session_cookie)
    if user["role"] not in {"finance", "admin", "demo"}:
        raise HTTPException(status_code=403, detail="Sales reports are not available for this role.")
    if period not in {"today", "this_month", "last_month"}:
        raise HTTPException(status_code=400, detail="Period must be today, this_month, or last_month.")
    if format not in {"csv", "pdf"}:
        raise HTTPException(status_code=400, detail="Format must be csv or pdf.")

    from app.reporting import generate_sales_report

    report = database.get_sales_report(period)
    content, media_type = generate_sales_report(report, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="sales-report-{period}.{format}"'},
    )


@app.post("/voice/text", response_model=TextResponse)
def voice_text(
    req: TextRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    """Text-only pipeline (skips STT/TTS) — same NLU -> Dialog Manager ->
    ERP path a real voice request takes. Use this to build/test the
    frontend, or as a typed fallback input mode."""
    user = auth.resolve_user(authorization, req.employee_id, session_cookie)
    session_id = f"{user['role']}:{user.get('employee_id') or 'demo'}:{req.session_id}"
    outcome = handle_utterance(session_id, req.text, user.get("employee_id"), user["role"])
    return outcome


@app.post("/voice/audio")
async def voice_audio(
    session_id: str = Form(...),
    employee_id: str | None = Form(None),
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="erp_session"),
):
    """Full voice pipeline: audio upload -> STT -> NLU -> Dialog Manager
    -> ERP -> TTS -> returns a .wav file to play back to the user.

    Requires an STT engine to be configured (see app/stt.py) and pyttsx3
    installed for TTS. Falls back to a clear error if neither is set up,
    so the rest of the app still runs for the text-only demo."""
    user = auth.resolve_user(authorization, employee_id, session_cookie)
    session_id = f"{user['role']}:{user.get('employee_id') or 'demo'}:{session_id}"
    employee_id = user.get("employee_id")

    try:
        from app import stt as stt_module
        from app import tts as tts_module
    except ImportError as e:
        return {"error": f"STT/TTS dependencies not installed: {e}"}

    # Save uploaded audio to a temp file
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        audio_path = tmp.name

    try:
        model_path = os.environ.get("VOSK_MODEL_PATH") or str(
            STATIC_DIR.parent / "models" / "vosk-model-small-en-us-0.15"
        )
        if not os.path.isdir(model_path):
            return {
                "error": (
                    "Vosk model not found. Download a Vosk model into "
                    f"{model_path}, or set VOSK_MODEL_PATH to its directory."
                )
            }
        engine = stt_module.get_engine(model_path)

        # Always normalize to 16kHz mono first -- see stt.preprocess_audio()
        # docstring for why this matters more than almost anything else here.
        clean_path = stt_module.preprocess_audio(audio_path)
        try:
            transcript = engine.transcribe(clean_path)
        finally:
            os.remove(clean_path)
    except Exception as e:
        return {"error": f"STT failed: {e}"}
    finally:
        os.remove(audio_path)

    outcome = handle_utterance(session_id, transcript, user.get("employee_id"), user["role"])

    out_wav = os.path.join(tempfile.gettempdir(), f"reply_{uuid.uuid4().hex}.wav")
    try:
        tts_module.synthesize_to_file(outcome["reply"], out_wav)
    except Exception as e:
        return {"transcript": transcript, "reply": outcome["reply"],
                "tts_error": str(e), "result": outcome["result"]}

    return FileResponse(out_wav, media_type="audio/wav", filename="reply.wav",
                         headers={"X-Transcript": transcript, "X-Reply-Text": outcome["reply"]})
