# SynthWarden — Product Specification

**Version:** 0.1.0 (MVP)  
**Last Updated:** January 30, 2026

---

## Overview

SynthWarden is a self-hosted notification engine for UniFi Protect sensors that provides smart, customizable alerts via Discord, Telegram, and Email.

### Problem Statement

UniFi Protect's native notifications are rudimentary:
- No duration-based alerts ("door open > 10 min")
- No time-based scheduling ("only notify at night")
- No throttling/cooldown (alert spam)
- No temperature threshold alerts
- Limited notification channels (app/email only)

The only current workaround is Home Assistant, which requires significant setup and is overkill for users who just want better notifications.

### Solution

A lightweight, Docker-based tool that:
1. Connects to UniFi Protect via local API
2. Provides a web UI for rule configuration
3. Sends smart notifications via Discord/Telegram/Email
4. Runs entirely locally with no cloud dependency

---

## Target Users

**Primary:** UniFi Protect owners who want better sensor notifications without setting up Home Assistant.

**Profile:**
- Runs UniFi Protect at home or small business
- Comfortable with Docker
- Wants "set and forget" notifications
- Values privacy (local-only)

**Not targeting:**
- Users who already have Home Assistant
- Enterprise deployments
- Non-technical users who can't run Docker

---

## MVP Features (v0.1)

### Core Functionality

1. **UniFi Protect Connection**
   - Connect via local API (IP + credentials)
   - WebSocket for real-time events
   - Auto-reconnect on connection loss
   - Support for UNVR, Cloud Key, Dream Machine

2. **Sensor Support**
   - Door/window contact sensors
   - Motion sensors
   - Temperature sensors (UP Sense)
   - Humidity sensors (UP Sense)
   - Doorbell ring events

3. **Rule Engine**
   - Trigger types:
     - State change (opened/closed)
     - Duration threshold (open > X minutes)
     - Value threshold (temp > X°F)
   - Conditions:
     - Time window (only between X and Y)
     - Day of week
   - Cooldowns (max 1 alert per X minutes)

4. **Notification Channels**
   - Discord (webhook)
   - Telegram (bot)
   - Email (SMTP)

5. **Web UI**
   - Sensor dashboard (current state)
   - Rule builder (sentence-style)
   - Notification channel setup
   - Alert history/log

### Non-Goals for MVP

- Mobile app
- Push notifications (use Discord/Telegram apps)
- Camera motion (focus on sensors first)
- Multi-user authentication
- Cloud sync/backup

---

## Technical Architecture

### Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12 |
| Framework | FastAPI + Uvicorn |
| UniFi Client | uiprotect library |
| Database | SQLite + aiosqlite |
| Frontend | Vue 3 (embedded SPA) |
| Container | Docker |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Docker Container                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FastAPI Application                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │   │
│  │  │ Web UI API  │  │ Rules Engine│  │ Notification    │  │   │
│  │  │ (Vue 3 SPA) │  │             │  │ Dispatcher      │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘  │   │
│  │         │                │                  │            │   │
│  │  ┌──────┴────────────────┴──────────────────┴───────┐   │   │
│  │  │              Core Event Loop                      │   │   │
│  │  └───────────────────────┬───────────────────────────┘   │   │
│  └──────────────────────────┼───────────────────────────────┘   │
│                             │                                    │
│  ┌──────────────────────────┼───────────────────────────────┐   │
│  │  ┌─────────────┐  ┌──────┴──────┐  ┌─────────────────┐   │   │
│  │  │ SQLite DB   │  │ uiprotect   │  │ Notifiers       │   │   │
│  │  │             │  │ WebSocket   │  │ - Discord       │   │   │
│  │  │             │  │             │  │ - Telegram      │   │   │
│  │  │             │  │             │  │ - Email         │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                             │                                    │
│  /data (volume)             │                                    │
└─────────────────────────────┼────────────────────────────────────┘
                              │ WebSocket
                              ▼
                    ┌─────────────────────┐
                    │  UniFi Protect NVR  │
                    └─────────────────────┘
```

### Data Model

```sql
-- Sensors (cached from UniFi)
CREATE TABLE sensors (
    id TEXT PRIMARY KEY,          -- UniFi sensor ID
    name TEXT,
    type TEXT,                    -- door, motion, temperature, etc.
    last_state TEXT,
    last_state_changed TIMESTAMP,
    battery_percent INTEGER,
    is_online BOOLEAN,
    raw_data JSON
);

-- Notification Rules
CREATE TABLE rules (
    id TEXT PRIMARY KEY,
    name TEXT,
    sensor_id TEXT,
    trigger_type TEXT,            -- state_change, duration, threshold
    trigger_config JSON,          -- {state: "open", duration_min: 10}
    conditions JSON,              -- {time_start: "22:00", time_end: "06:00"}
    destinations JSON,            -- [{type: "discord", channel_id: "..."}]
    cooldown_minutes INTEGER DEFAULT 30,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Notification Channels
CREATE TABLE channels (
    id TEXT PRIMARY KEY,
    name TEXT,                    -- "Home Alerts"
    type TEXT,                    -- discord, telegram, email
    config JSON,                  -- {webhook_url: "..."} or {bot_token, chat_id}
    created_at TIMESTAMP
);

-- Alert History
CREATE TABLE alert_log (
    id INTEGER PRIMARY KEY,
    rule_id TEXT,
    sensor_id TEXT,
    triggered_at TIMESTAMP,
    resolved_at TIMESTAMP,
    destinations_sent JSON,       -- [{channel_id, success, error}]
    event_data JSON
);

-- Sensor State Tracking (for duration alerts)
CREATE TABLE sensor_state (
    sensor_id TEXT PRIMARY KEY,
    current_state TEXT,
    state_since TIMESTAMP,
    alert_sent BOOLEAN DEFAULT FALSE
);
```

---

## User Interface

### Screens

1. **Dashboard** — Sensor status cards (state, duration, battery)
2. **Rules** — List of rules with enable/disable toggle
3. **Rule Editor** — Sentence-builder interface
4. **Channels** — Notification channel configuration
5. **History** — Alert log with filters
6. **Settings** — UniFi connection, general config

### Rule Builder UX

"Sentence builder" pattern for intuitive rule creation:

```
When [▼ Main Garage Door] is [▼ open] for [▼ more than]
[  10  ] [▼ minutes], notify via [▼ Discord]

☐ Only between 10:00 PM and 6:00 AM
☐ Repeat alert every [  30  ] minutes while open
```

### Quick Templates

One-click starting points:
- 🚗 "Garage left open" — Open > 15 min after 10 PM
- 🚪 "Unexpected entry" — Door opened during away hours
- 🔔 "Doorbell alert" — Ring, notify immediately
- ❄️ "Freeze warning" — Temp below 35°F

---

## Notification Format

### Discord

```
🚨 SynthWarden Alert

Main Garage Door has been OPEN for 15 minutes

📍 Sensor: Main Garage Door
⏱️ Open since: 10:45 PM
🕐 Current time: 11:00 PM

Rule: Garage left open
```

### Telegram

```
🚨 Main Garage Door — OPEN 15 min

Open since: 10:45 PM
Rule: Garage left open
```

### Email

Subject: `🚨 SynthWarden: Main Garage Door open 15 min`

---

## Security

1. **Credentials** — Stored encrypted (Fernet) in SQLite
2. **Web UI** — Binds to localhost by default; optional auth for LAN access
3. **UniFi Account** — Recommend creating a local-only admin (not main account)
4. **No Cloud** — All data stays local

---

## Installation

### Docker (Recommended)

```yaml
version: '3.8'
services:
  synthwarden:
    image: synthwarden/synthwarden:latest
    container_name: synthwarden
    restart: unless-stopped
    ports:
      - "8099:8000"
    volumes:
      - ./data:/app/data
    environment:
      - TZ=America/Chicago
    env_file:
      - .env
```

### Environment Variables

```env
UNIFI_HOST=192.168.1.1
UNIFI_USER=synthwarden-user
UNIFI_PASS=your-password
SECRET_KEY=random-32-char-string
```

---

## Roadmap

### v0.1 (MVP)
- [x] UniFi Protect connection
- [x] Basic rule engine
- [x] Discord/Telegram/Email
- [x] Web UI
- [x] Docker packaging

### v0.2
- [ ] Camera motion events
- [ ] Geofencing (home/away)
- [ ] Rule import/export
- [ ] Unraid Community Apps listing

### v0.3
- [ ] Multi-sensor conditions (AND/OR)
- [ ] Humidity threshold alerts
- [ ] Light level alerts
- [ ] Notification batching/digest

### Future
- [ ] Home Assistant add-on
- [ ] Prometheus metrics
- [ ] Mobile app (maybe)
- [ ] Pro tier features

---

## Business Model

**Open Source Core + Paid Pro Tier**

| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | Core monitoring, 3 channels, basic rules |
| Pro | $29 one-time | Unlimited rules, advanced conditions, priority support |

---

## Research References

- [User Research Report](research/unifi-user-research.md)
- [Competitive Analysis](research/competitive-analysis.md)
- [Technical Architecture](research/tech-architecture.md)
- [UX Design](research/ux-design.md)
- [Business Strategy](research/business-strategy.md)
