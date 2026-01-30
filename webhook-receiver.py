#!/usr/bin/env python3
"""Simple webhook receiver for SynthWarden → Clawdbot integration.

Receives alerts from SynthWarden and writes them to a file that Clawdbot polls.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)

ALERTS_FILE = Path.home() / "clawd" / "data" / "synthwarden-alerts.json"

def ensure_alerts_file():
    """Ensure alerts file exists."""
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ALERTS_FILE.exists():
        ALERTS_FILE.write_text("[]")

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Receive alert from SynthWarden."""
    try:
        data = request.json
        data["received_at"] = datetime.now().isoformat()
        data["processed"] = False
        
        # Load existing alerts
        ensure_alerts_file()
        alerts = json.loads(ALERTS_FILE.read_text())
        
        # Add new alert
        alerts.append(data)
        
        # Keep only last 50 alerts
        alerts = alerts[-50:]
        
        # Save
        ALERTS_FILE.write_text(json.dumps(alerts, indent=2, default=str))
        
        print(f"[{datetime.now()}] Received alert: {data.get('message', 'unknown')}")
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    ensure_alerts_file()
    print("SynthWarden webhook receiver starting on port 8098...")
    app.run(host="0.0.0.0", port=8098)
