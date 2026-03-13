import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Config ---

CALENDAR_MODE = os.environ.get("CALENDAR_MODE", "local")
CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
SERVICE_ACCOUNT_KEY = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
CONFIG_PATH = os.environ.get("PTO_CONFIG_PATH", "/app/config/pto-config.json")
LOCAL_DB_PATH = os.environ.get("LOCAL_DB_PATH", "/app/data/planto.db")

DEFAULT_CONFIG = {
    "year": datetime.now().year,
    "pto_days": 15,
    "floating_holidays": 5,
    "company_holidays": [
        {"name": "New Year's Day", "date": "01-01"},
        {"name": "Memorial Day", "date": "05-25"},
        {"name": "Independence Day", "date": "07-03"},
        {"name": "Labor Day", "date": "09-07"},
        {"name": "Thanksgiving", "date": "11-26"},
        {"name": "Day after Thanksgiving", "date": "11-27"},
        {"name": "Christmas", "date": "12-25"},
    ],
}


# --- Local SQLite storage ---

def init_local_db():
    Path(LOCAL_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            date TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def get_local_db():
    return sqlite3.connect(LOCAL_DB_PATH)


def load_persisted_config():
    """Load config from DB, falling back to file then defaults."""
    db = get_local_db()
    row = db.execute("SELECT value FROM config WHERE key = 'pto_config'").fetchone()
    db.close()
    if row:
        return json.loads(row[0])

    # First run: seed from config file if it exists
    config_file = Path(CONFIG_PATH)
    if config_file.exists():
        with open(config_file) as f:
            file_config = json.load(f)
        # Normalize holiday dates to MM-DD format (strip year prefix if present)
        for h in file_config.get("company_holidays", []):
            d = h["date"]
            if len(d) == 10:  # YYYY-MM-DD
                h["date"] = d[5:]
        save_persisted_config(file_config)
        return file_config

    save_persisted_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_persisted_config(cfg):
    db = get_local_db()
    db.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES ('pto_config', ?)",
        (json.dumps(cfg),),
    )
    db.commit()
    db.close()


init_local_db()
PTO_CONFIG = load_persisted_config()


# --- Google Calendar ---

def get_calendar_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build as build_service

    if not SERVICE_ACCOUNT_KEY or not Path(SERVICE_ACCOUNT_KEY).exists():
        raise HTTPException(503, "Google service account key not configured")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_KEY,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build_service("calendar", "v3", credentials=creds)


# --- Models ---

class EventCreate(BaseModel):
    title: str
    date: str  # YYYY-MM-DD


class EventUpdate(BaseModel):
    date: str  # YYYY-MM-DD


class HolidayConfig(BaseModel):
    name: str
    date: str  # MM-DD


class ConfigUpdate(BaseModel):
    year: Optional[int] = None
    pto_days: Optional[int] = None
    floating_holidays: Optional[int] = None
    company_holidays: Optional[List[HolidayConfig]] = None


# --- Routes ---

@app.get("/config")
def get_config():
    now = datetime.now()
    min_year = now.year - 5
    max_year = now.year + 10
    # Build full-date holidays for the selected year
    year = PTO_CONFIG["year"]
    holidays_with_year = []
    for h in PTO_CONFIG.get("company_holidays", []):
        d = h["date"]
        full_date = f"{year}-{d}" if len(d) == 5 else d
        holidays_with_year.append({"name": h["name"], "date": full_date})

    return {
        "year": year,
        "pto_days": PTO_CONFIG["pto_days"],
        "floating_holidays": PTO_CONFIG["floating_holidays"],
        "company_holidays": holidays_with_year,
        "company_holidays_raw": PTO_CONFIG.get("company_holidays", []),
        "calendar_mode": CALENDAR_MODE,
        "min_year": min_year,
        "max_year": max_year,
    }


@app.put("/config")
def update_config(update: ConfigUpdate):
    global PTO_CONFIG
    if update.year is not None:
        now = datetime.now()
        if not (now.year - 5 <= update.year <= now.year + 10):
            raise HTTPException(400, "Year out of range")
        PTO_CONFIG["year"] = update.year
    if update.pto_days is not None:
        if update.pto_days < 0 or update.pto_days > 365:
            raise HTTPException(400, "Invalid PTO days")
        PTO_CONFIG["pto_days"] = update.pto_days
    if update.floating_holidays is not None:
        if update.floating_holidays < 0 or update.floating_holidays > 365:
            raise HTTPException(400, "Invalid floating holidays")
        PTO_CONFIG["floating_holidays"] = update.floating_holidays
    if update.company_holidays is not None:
        PTO_CONFIG["company_holidays"] = [
            {"name": h.name, "date": h.date} for h in update.company_holidays
        ]
    save_persisted_config(PTO_CONFIG)
    return get_config()


@app.get("/events")
def list_events(year: Optional[int] = None):
    y = year or PTO_CONFIG["year"]
    if CALENDAR_MODE == "local":
        return _list_events_local(y)
    return _list_events_google(y)


@app.post("/events")
def create_event(event: EventCreate):
    if CALENDAR_MODE == "local":
        return _create_event_local(event)
    return _create_event_google(event)


@app.put("/events/{event_id}")
def update_event(event_id: str, event: EventUpdate):
    if CALENDAR_MODE == "local":
        return _update_event_local(event_id, event)
    return _update_event_google(event_id, event)


@app.delete("/events/{event_id}")
def delete_event(event_id: str):
    if CALENDAR_MODE == "local":
        return _delete_event_local(event_id)
    return _delete_event_google(event_id)


# --- Local implementations ---

def _list_events_local(year: int):
    db = get_local_db()
    rows = db.execute(
        "SELECT id, title, date FROM events WHERE date >= ? AND date <= ? ORDER BY date",
        (f"{year}-01-01", f"{year}-12-31"),
    ).fetchall()
    db.close()
    return [{"id": r[0], "title": r[1], "date": r[2]} for r in rows]


def _create_event_local(event: EventCreate):
    event_id = str(uuid.uuid4())
    db = get_local_db()
    db.execute("INSERT INTO events (id, title, date) VALUES (?, ?, ?)",
               (event_id, event.title, event.date))
    db.commit()
    db.close()
    return {"id": event_id, "title": event.title, "date": event.date}


def _update_event_local(event_id: str, event: EventUpdate):
    db = get_local_db()
    cur = db.execute("UPDATE events SET date = ? WHERE id = ?", (event.date, event_id))
    if cur.rowcount == 0:
        db.close()
        raise HTTPException(404, "Event not found")
    title = db.execute("SELECT title FROM events WHERE id = ?", (event_id,)).fetchone()[0]
    db.commit()
    db.close()
    return {"id": event_id, "title": title, "date": event.date}


def _delete_event_local(event_id: str):
    db = get_local_db()
    cur = db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    if cur.rowcount == 0:
        db.close()
        raise HTTPException(404, "Event not found")
    db.commit()
    db.close()
    return {"ok": True}


# --- Google implementations ---

def _list_events_google(year: int):
    service = get_calendar_service()
    results = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=f"{year}-01-01T00:00:00Z",
        timeMax=f"{year}-12-31T23:59:59Z",
        singleEvents=True,
        orderBy="startTime",
        maxResults=500,
    ).execute()

    events = []
    valid_titles = (
        ["PTO", "Floating Holiday"]
        + [h["name"] for h in PTO_CONFIG.get("company_holidays", [])]
    )
    for item in results.get("items", []):
        title = item.get("summary", "")
        if title in valid_titles:
            start = item["start"].get("date", item["start"].get("dateTime", "")[:10])
            events.append({"id": item["id"], "title": title, "date": start})
    return events


def _create_event_google(event: EventCreate):
    service = get_calendar_service()
    body = {
        "summary": event.title,
        "start": {"date": event.date},
        "end": {"date": event.date},
    }
    created = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return {"id": created["id"], "title": event.title, "date": event.date}


def _update_event_google(event_id: str, event: EventUpdate):
    service = get_calendar_service()
    existing = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    existing["start"] = {"date": event.date}
    existing["end"] = {"date": event.date}
    updated = service.events().update(
        calendarId=CALENDAR_ID, eventId=event_id, body=existing
    ).execute()
    return {"id": updated["id"], "title": updated["summary"], "date": event.date}


def _delete_event_google(event_id: str):
    service = get_calendar_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return {"ok": True}


# Serve frontend static files
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(str(frontend_dir / "index.html"))
