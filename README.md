# SynthWarden

> Smart notifications for UniFi Protect sensors. Because "door opened" isn't enough.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://hub.docker.com/r/synthwarden/synthwarden)

## What is SynthWarden?

SynthWarden is a self-hosted notification engine for UniFi Protect sensors. It connects to your local UniFi Protect system and sends smart, customizable alerts via Discord, Telegram, or Email.

**Native UniFi Protect gives you:** "Garage door opened"  
**SynthWarden gives you:** "Garage door has been open for 15 minutes (it's 11 PM)"

## Features

- 🚪 **Duration Alerts** — "Alert if door open > 10 minutes"
- 🌙 **Time-Based Rules** — "Only notify between 10 PM and 6 AM"
- 🌡️ **Temperature Thresholds** — "Alert if freezer goes above 32°F"
- 🔔 **Multi-Channel** — Discord, Telegram, Email, OpenClaw
- ⏰ **Cooldowns** — No more alert spam
- 📊 **Alert History** — Review past notifications
- 🏠 **100% Local** — No cloud, your data stays yours

## Quick Start

```bash
docker run -d \
  --name synthwarden \
  -p 8099:8000 \
  -v synthwarden-data:/app/data \
  -e UNIFI_HOST=192.168.1.1 \
  -e UNIFI_USER=admin \
  -e UNIFI_PASS=yourpassword \
  synthwarden/synthwarden:latest
```

Then open `http://localhost:8099` to configure your rules.

## Documentation

- [Installation Guide](docs/installation.md)
- [Configuration](docs/configuration.md)
- [Creating Rules](docs/rules.md)
- [Notification Channels](docs/notifications.md)
- [API Reference](docs/api.md)

## OpenClaw Integration

SynthWarden integrates directly with [OpenClaw](https://github.com/openclaw/openclaw) to send alerts through your AI assistant. Add a **OpenClaw Gateway** channel in Settings and configure:

- **Gateway URL** — Your OpenClaw gateway address (e.g., `http://localhost:8080`)
- **Target** — Discord user (`user:123456789`) or channel ID
- **Token** — Gateway token if authentication is required

Alerts are sent directly through OpenClaw's message API, so your AI assistant can see and respond to sensor alerts.

## Why SynthWarden?

UniFi Protect's native notifications are binary — you get every event or nothing. No scheduling, no duration alerts, no conditions. The only alternative is Home Assistant, which is overkill if you just want better notifications.

SynthWarden fills that gap: **5-minute setup, smart defaults, just works.**

## Requirements

- UniFi Protect system (UNVR, Cloud Key Gen2+, or Dream Machine)
- Docker (or Python 3.11+)
- Network access to your UniFi Protect controller

## Supported Sensors

- UP Door/Window Sensors
- UP Sense (contact, motion, temperature, humidity, light)
- UniFi Protect Doorbell (ring events)
- Camera motion events

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License. See [LICENSE](LICENSE).

## Disclaimer

SynthWarden is not affiliated with Ubiquiti Inc. UniFi and UniFi Protect are trademarks of Ubiquiti Inc. This is an unofficial third-party tool that uses the local UniFi Protect API.

---

**Website:** [synthwarden.com](https://synthwarden.com)  
**Discord:** Coming soon
