"""
UpQuest â AI-Powered Health \u0026 Routine App
Backend: FastAPI (Python 3.12)
LLM: xAI Grok API (OpenAI-compatible)
DB/Auth/Storage: Supabase
"""

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import json
import os
import uuid
import io
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import date, datetime

from supabase_client import get_supabase_client
from pdf_parser import parse_bloodwork_pdf
from schedule_generator import build_schedule_prompt, parse_schedule_response
from models import (
    UserStats,
    ScheduleRequest,
    ProfileUpdateRequest,
    ProgressEntry,
)
import stripe_routes

app = FastAPI(
    title="UpQuest API",
    description="AI-powered health routine generator",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stripe_routes.router, prefix="/stripe", tags=["Payments"])

from openai import OpenAI

grok_client = OpenAI(
    api_key=os.environ["XAI_API_KEY"],
    base_url="https://api.x.ai/v1",
)

GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-latest")


def require_auth(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed token.")
    token = authorization.split(" ", 1)[1]
    supabase = get_supabase_client()
    try:
        user = supabase.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Invalid token.")
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Token validation failed.")


def check_premium(user_id: str) -\u003e bool:
    supabase = get_supabase_client()
    result = (supabase.table("subscriptions").select("status, period_end").eq("user_id", user_id).maybe_single().execute())
    if not result.data: return False
    sub = result.data
    if sub["status"] == "active":
        return datetime.fromisoformat(sub["period_end"]) \u003e datetime.utcnow()
    return False


def check_free_quota(user_id: str) -\u003e bool:
    supabase = get_supabase_client()
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = (supabase.table("schedules").select("id", count="exact").eq("user_id", user_id).gte("created_at", month_start.isoformat()).execute())
    return (result.count or 0) \u003c 1


@app.get("/", tags=["Health"])
def root():
    return {"status": "UpQuest API is live ð", "version": "1.0.0"}


@app.post("/profile", tags=["User"])
async def upsert_profile(payload: ProfileUpdateRequest, user=Depends(require_auth)):
    supabase = get_supabase_client()
    data = {"id": user.id, "stats": payload.stats.dict(), "goals": payload.goals, "updated_at": datetime.utcnow().isoformat()}
    result = supabase.table("users").upsert(data).execute()
    return {"success": True, "data": result.data}


@app.get("/profile", tags=["User"])
async def get_profile(user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("users").select("*").eq("id", user.id).single().execute())
    return {"profile": result.data, "is_premium": check_premium(user.id)}


@app.post("/upload-bloodwork", tags=["Bloodwork"])
async def upload_bloodwork(file: UploadFile = File(...), user=Depends(require_auth)):
    if not check_premium(user.id):
        raise HTTPException(status_code=403, detail="Bloodwork upload is a Premium feature.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    file_bytes = await file.read()
    extracted = parse_bloodwork_pdf(io.BytesIO(file_bytes))
    if len(extracted.get("values", {})) \u003c 3:
        fallback_prompt = ("Extract all lab values from the following bloodwork text. Return ONLY valid JSON like: {\"triglycerides\": 169}\
\
"
                            f"Text:\
{extracted.get('raw_text', '')[:6000]}")
        resp = grok_client.chat.completions.create(model=GROK_MODEL, messages=[{"role": "user", "content": fallback_prompt}], temperature=0.2)
        try:
            extracted["values"].update(json.loads(resp.choices[0].message.content))
        except json.JSONDecodeError: pass
    supabase = get_supabase_client()
    storage_path = f"{user.id}/{uuid.uuid4()}.pdf"
    supabase.storage.from_("bloodwork").upload(storage_path, file_bytes, {"content-type": "application/pdf"})
    public_url = supabase.storage.from_("bloodwork").get_public_url(storage_path)
    result = supabase.table("bloodwork_uploads").insert({"user_id": user.id, "file_url": public_url, "extracted_data": extracted, "uploaded_at": datetime.utcnow().isoformat()}).execute()
    return {"success": True, "extracted": extracted, "record_id": result.data[0]["id"]}


@app.get("/bloodwork", tags=["Bloodwork"])
async def list_bloodwork(user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("bloodwork_uploads").select("*").eq("user_id", user.id).order("uploaded_at", desc=True).execute())
    return {"uploads": result.data}


@app.post("/generate-schedule", tags=["Schedule"])
async def generate_schedule(payload: ScheduleRequest, user=Depends(require_auth)):
    is_premium = check_premium(user.id)
    if not is_premium:
        if not check_free_quota(user.id):
            raise HTTPException(status_code=403, detail="Free plan limit reached (1 schedule/month). Upgrade to Premium.")
        payload.bloodwork_summary = None
    if is_premium and not payload.bloodwork_summary:
        supabase = get_supabase_client()
        bw = (supabase.table("bloodwork_uploads").select("extracted_data").eq("user_id", user.id).order("uploaded_at", desc=True).limit(1).maybe_single().execute())
        if bw.data: payload.bloodwork_summary = bw.data["extracted_data"].get("values", {})
    prompt = build_schedule_prompt(stats=payload.stats.dict(), goals=payload.goals, bloodwork=payload.bloodwork_summary, week_start=payload.week_start or str(date.today()))
    response = grok_client.chat.completions.create(model=GROK_MODEL, temperature=0.7, max_tokens=8000,
        messages=[{"role": "system", "content": "You are UpQuest AI â an expert health caretaker. Always respond with ONLY valid JSON. No markdown, no prose."},
        {"role": "user", "content": prompt}])
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
    raw = raw.strip()
    try: schedule_json = json.loads(raw)
    except json.JSONDecodeError: schedule_json = parse_schedule_response(raw)
    supabase = get_supabase_client()
    result = supabase.table("schedules").insert({"user_id": user.id, "week_start": payload.week_start or str(date.today()), "full_schedule": schedule_json, "ical_url": None, "created_at": datetime.utcnow().isoformat()}).execute()
    return {"success": True, "schedule_id": result.data[0]["id"], "schedule": schedule_json, "is_premium": is_premium}


@app.get("/schedules", tags=["Schedule"])
async def list_schedules(user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("schedules").select("id, week_start, created_at, ical_url").eq("user_id", user.id).order("week_start", desc=True).execute())
    return {"schedules": result.data}


@app.get("/schedules/{schedule_id}", tags=["Schedule"])
async def get_schedule(schedule_id: str, user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("schedules").select("*").eq("id", schedule_id).eq("user_id", user.id).single().execute())
    if not result.data: raise HTTPException(status_code=404, detail="Schedule not found.")
    return {"schedule": result.data}


@app.get("/schedules/{schedule_id}/ical", tags=["Calendar"])
async def export_ical(schedule_id: str, user=Depends(require_auth)):
    from icalendar import Calendar, Event as ICalEvent
    from datetime import timedelta
    supabase = get_supabase_client()
    result = (supabase.table("schedules").select("*").eq("id", schedule_id).eq("user_id", user.id).single().execute())
    if not result.data: raise HTTPException(status_code=404, detail="Schedule not found.")
    sched = result.data
    full = sched["full_schedule"]
    week_start_str = sched["week_start"]
    week_start = date.fromisoformat(week_start_str)
    cal = Calendar()
    cal.add("prodid", "-//UpQuest AI//upquest.app//EN")
    cal.add("version", "2.0")
    cal.add("calname", f"UpQuest Week of {week_start_str}")
    for i, day_name in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]):
        day_date = week_start + timedelta(days=i)
        for time_slot, activity in full.get("days", {}).get(day_name, {}).items():
            try: hour, minute = _parse_time(time_slot)
            except: continue
            event = ICalEvent()
            event.add("summary", f"UpQuest â {activity[:60]}")
            event.add("dtstart", datetime(day_date.year, day_date.month, day_date.day, hour, minute))
            event.add("dtend", datetime(day_date.year, day_date.month, day_date.day, hour, minute) + timedelta(minutes=30))
            event.add("description", activity)
            event.add("uid", f"{schedule_id}-{i}-{hour}{minute}@upquest.app")
            cal.add_component(event)
    ical_bytes = cal.to_ical()
    supabase.table("schedules").update({"ical_url": f"/schedules/{schedule_id}/ical"}).eq("id", schedule_id).execute()
    return StreamingResponse(io.BytesIO(ical_bytes), media_type="text/calendar", headers={"Content-Disposition": f"attachment; filename=upquest-week-{week_start_str}.ics"})


def _parse_time(time_str: str):
    time_str = time_str.strip()
    if "AM" in time_str.upper() or "PM" in time_str.upper():
        t = datetime.strptime(time_str.upper().replace(" ", ""), "%I:%M%p")
    else:
        t = datetime.strptime(time_str, "%H:%M")
    return t.hour, t.minute


@app.post("/progress", tags=["Progress"])
async def log_progress(entry: ProgressEntry, user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = supabase.table("progress_logs").insert({"user_id": user.id, "logged_at": datetime.utcnow().isoformat(), **entry.dict()}).execute()
    return {"success": True, "data": result.data}


@app.get("/progress", tags=["Progress"])
async def get_progress(user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("progress_logs").select("*").eq("user_id", user.id).order("logged_at", desc=True).execute())
    return {"logs": result.data}


@app.get("/subscription", tags=["Payments"])
async def get_subscription(user=Depends(require_auth)):
    supabase = get_supabase_client()
    result = (supabase.table("subscriptions").select("*").eq("user_id", user.id).maybe_single().execute())
    return {"is_premium": check_premium(user.id), "subscription": result.data}
# ─────────────────────────────────────────────────────────────────────────────
# PASTE THIS AT THE VERY BOTTOM OF main.py IN GITHUB, THEN COMMIT
# Also update the "from typing import Optional" line to add: List, Dict, Any
# And add "from pydantic import BaseModel" after the existing imports if missing
# ─────────────────────────────────────────────────────────────────────────────


# ── Plan Chat (no auth required) ─────────────────────────────────────────────

class PlanChatMessage(BaseModel):
    role: str
    content: str

class PlanChatRequest(BaseModel):
    messages: List[PlanChatMessage] = []
    stats: Dict[str, Any] = {}
    goals: List[str] = []
    action: str = "chat"   # "chat" | "generate" | "modify"
    current_plan: Any = None


@app.post("/plan-chat", tags=["Plan"])
async def plan_chat(payload: PlanChatRequest):
    """AI health coach — no auth required. Chat or generate a plan."""

    if payload.action in ("generate", "modify"):
        week_start = str(date.today())
        prompt = build_schedule_prompt(
            stats=payload.stats,
            goals=payload.goals,
            bloodwork=None,
            week_start=week_start,
        )
        if payload.action == "modify" and payload.current_plan:
            prompt += (
                "\n\nThe user already has a plan. Modify it based on the "
                "conversation. Return the same JSON structure.\n"
                + json.dumps(payload.current_plan)
            )
        messages_for_grok = [{"role": "system", "content": prompt}] + [
            {"role": m.role, "content": m.content} for m in payload.messages
        ]
        response = grok_client.chat.completions.create(
            model=GROK_MODEL,
            temperature=0.7,
            messages=messages_for_grok,
        )
        raw = response.choices[0].message.content
        try:
            schedule = parse_schedule_response(raw)
        except Exception:
            schedule = None
        label = "updated" if payload.action == "modify" else "ready"
        return {"message": f"Your plan is {label}!", "schedule": schedule}

    # ── Chat mode ────────────────────────────────────────────────────────────
    system_prompt = (
        "You are an expert AI health coach having a warm, concise conversation "
        "to understand the user's lifestyle so you can build a personalized health plan. "
        "Gather info about: sleep quality, daily activity level, diet/eating habits, "
        "stress levels, and specific health goals. "
        "Keep each response SHORT — 2 to 4 sentences max. Be conversational and warm. "
        "Acknowledge what the user shared before asking the next question. "
        "After 3-4 exchanges tell them you have enough info and they can tap Generate."
    )
    messages_for_grok = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in payload.messages
    ]
    response = grok_client.chat.completions.create(
        model=GROK_MODEL,
        temperature=0.85,
        max_tokens=220,
        messages=messages_for_grok,
    )
    return {"message": response.choices[0].message.content}
