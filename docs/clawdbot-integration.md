# Clawdbot Integration

SynthWarden integrates directly with [Clawdbot](https://github.com/clawdbot/clawdbot) to send alerts through your AI assistant.

## Setup

### 1. Add Clawdbot Channel

In SynthWarden Settings → Notification Channels:

1. Click **Add Channel**
2. Select **Clawdbot Gateway** as the type
3. Fill in:
   - **Name**: Descriptive name (e.g., "My Clawdbot")
   - **Gateway URL**: Your Clawdbot gateway address
   - **Target**: Where to send alerts
   - **Token**: Gateway authentication token (if required)

### 2. Configure Target

The **Target** field accepts:

| Format | Example | Description |
|--------|---------|-------------|
| `user:ID` | `user:130447280661594112` | Discord user DM |
| Channel ID | `1234567890` | Discord channel |
| `@username` | `@arlandw` | Telegram username |

### 3. Gateway URL

Common configurations:

```
# Local Clawdbot
http://localhost:8080

# Docker (from another container)
http://host.docker.internal:8080

# Remote server
http://192.168.1.100:8080
```

## How It Works

```
Sensor Event → SynthWarden Rule → Clawdbot Gateway → Discord/Telegram
```

1. UniFi Protect sensor triggers (door opens, battery low, etc.)
2. SynthWarden evaluates rules and conditions
3. If rule matches, SynthWarden POSTs to Clawdbot's `/api/message` endpoint
4. Clawdbot delivers the alert to Discord/Telegram/etc.

## Alert Format

Alerts sent through Clawdbot look like:

```
🚨 **SynthWarden Alert**

**Front Door** is open

📍 Sensor: Front Door
🕐 Time: 10:45 PM
📋 Rule: Night Alert
```

## API Integration

If you prefer programmatic integration, use the Clawdbot API endpoints:

### Get Sensor Status

```bash
curl http://localhost:8099/api/clawdbot/sensors
```

### Get Summary

```bash
curl http://localhost:8099/api/clawdbot/summary
```

Response:
```json
{
  "connected": true,
  "sensor_count": 7,
  "sensors": [...],
  "active_alerts": 0,
  "last_alert": "2024-01-30T22:45:00Z"
}
```

### Register Webhook

For custom integrations, register a webhook:

```bash
curl -X POST http://localhost:8099/api/clawdbot/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://your-endpoint/webhook",
    "events": ["alert", "state_change"]
  }'
```

## Troubleshooting

### "Connection refused" errors

- Ensure Clawdbot gateway is running
- Check firewall allows connection between SynthWarden and Clawdbot
- If using Docker, use `host.docker.internal` instead of `localhost`

### Alerts not delivering

1. Test the channel in SynthWarden Settings
2. Check Clawdbot logs for errors
3. Verify the target user/channel ID is correct
4. Ensure Clawdbot has permissions to send to that target

### Authentication errors

If your Clawdbot requires authentication:
1. Generate a gateway token in Clawdbot config
2. Add the token to the Clawdbot channel in SynthWarden
