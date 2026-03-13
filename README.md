# PlanTO

A self-hosted drag-and-drop PTO planning tool. Visually allocate your vacation days, floating holidays, and company holidays onto a calendar by dragging chips from a pool. Runs locally with SQLite or syncs with Google Calendar.

## Quick Start

```bash
docker compose up -d
```

Open **http://localhost:3456**. That's it — the app runs in local mode by default with no external dependencies.

### Building from source

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

## How It Works

- **Sidebar (desktop) / bottom trays (mobile)** hold your unscheduled day chips, organized by type:
  - **PTO Days** — general vacation (blue)
  - **Floating Holidays** — flexible holidays (green)
  - **Company Holidays** — fixed holidays with names (red)
- **Drag a chip onto a calendar date** to schedule it
- **Click a scheduled event** to unschedule it (returns the chip to the pool)
- **Drag an existing event** to a different date to reschedule it
- Remaining counts update in real time

## Configuration

All settings are configurable from the in-app **Settings** panel (gear icon):

- Number of PTO days
- Number of floating holidays
- Company holidays (name + date) — add, remove, or edit

Settings persist in SQLite across container restarts.

### Year Selection

Use the year selector in the sidebar/header to switch between years. The range spans 5 years in the past to 10 years in the future. Events are stored per-year.

### Initial Defaults

The app ships with sample 2026 US holidays in `config/pto-config.json`. On first run, these are imported into the database. After that, all changes are made through the Settings UI.

```json
{
  "year": 2026,
  "pto_days": 15,
  "floating_holidays": 5,
  "company_holidays": [
    { "name": "New Year's Day", "date": "01-01" },
    { "name": "Memorial Day", "date": "05-25" },
    { "name": "Independence Day", "date": "07-03" },
    { "name": "Labor Day", "date": "09-07" },
    { "name": "Thanksgiving", "date": "11-26" },
    { "name": "Day after Thanksgiving", "date": "11-27" },
    { "name": "Christmas", "date": "12-25" }
  ]
}
```

## Calendar Modes

### Local Mode (default)

Events are stored in a SQLite database (`data/planto.db`), persisted via a Docker volume. No external accounts or APIs required.

### Google Calendar Mode (untested)

Syncs events with a Google Calendar. **Note: this mode has not been tested and may require adjustments.** To enable:

1. Create a **service account** in [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Enable the **Google Calendar API** for the project
3. Download the service account JSON key file
4. Share your target calendar with the service account's email address (give it "Make changes to events" permission)
5. Update your `.env`:

```env
CALENDAR_MODE=google
GOOGLE_CALENDAR_ID=your-calendar-id@group.calendar.google.com
GOOGLE_SERVICE_ACCOUNT_KEY=./service-account.json
```

Events are named in Google Calendar as:
- `PTO` for vacation days
- `Floating Holiday` for floating holidays
- `{Holiday Name}` for company holidays (e.g., `Thanksgiving`)

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CALENDAR_MODE` | `local` | `local` or `google` |
| `GOOGLE_CALENDAR_ID` | `primary` | Google Calendar ID (google mode only) |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | — | Path to service account JSON key (google mode only) |
| `PTO_CONFIG_PATH` | `/app/config/pto-config.json` | Initial config file path |
| `LOCAL_DB_PATH` | `/app/data/planto.db` | SQLite database path |

## Project Structure

```
PlanTO/
├── frontend/
│   └── index.html          # Single-file frontend (FullCalendar + vanilla JS)
├── backend/
│   ├── main.py              # FastAPI backend
│   └── requirements.txt
├── config/
│   └── pto-config.json      # Default PTO configuration
├── docker-compose.yml       # Pull from GHCR
├── docker-compose.dev.yml   # Build from source
├── Dockerfile
├── .env.example
└── .gitignore
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/config` | Get current configuration |
| `PUT` | `/config` | Update configuration (year, days, holidays) |
| `GET` | `/events` | List all PTO events for the selected year |
| `POST` | `/events` | Create an event `{title, date}` |
| `PUT` | `/events/:id` | Move an event to a new date `{date}` |
| `DELETE` | `/events/:id` | Delete an event |

## Tech Stack

- **Frontend**: Vanilla JS, [FullCalendar v6](https://fullcalendar.io/), Cormorant Garamond + DM Sans
- **Backend**: Python, [FastAPI](https://fastapi.tiangolo.com/), SQLite
- **Containerization**: Docker, Docker Compose
