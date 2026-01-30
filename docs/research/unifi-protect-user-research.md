# UniFi Protect Sensors & Notifications - User Research Report

**Compiled:** January 30, 2026  
**Sources:** Reddit (r/Ubiquiti, r/UniFi, r/homeassistant), UniFi Community Forums, Feature Request Tracker

---

## Executive Summary

UniFi Protect users consistently express frustration with the **limited automation and notification capabilities** of the platform. While the hardware (cameras, sensors) is praised, the software's notification system is viewed as rudimentary compared to competitors. The most common workaround is integrating with **Home Assistant** via the UniFi Protect integration.

---

## 1. Missing Notification Features (Most Requested)

### Duration-Based Alerts
**Pain Point:** Users cannot set alerts for sensors left in a state too long.

> "I want to know if my garage door has been open for more than 10 minutes, not every single time it opens." — r/Ubiquiti

> "Why can't I get an alert if a door is left open for X minutes? This seems like basic functionality." — UniFi Community Forums

**Specific requests:**
- Door left open > X minutes
- Motion detected for extended period (loitering detection)
- Temperature sensor out of range for > X minutes

### Schedule-Based Notifications
**Pain Point:** No ability to set notification schedules or "armed" modes.

> "I only want door notifications at night. During the day, my kids go in and out constantly. The noise is unbearable." — r/Ubiquiti

> "Need an 'Away mode' that enables all alerts vs 'Home mode' that only alerts on external doors." — UniFi Community

**Requests:**
- Time-based notification rules (e.g., only notify 10pm-6am)
- Geofencing to auto-enable/disable
- Manual arm/disarm modes
- Per-sensor schedules

### Notification Grouping & Throttling
**Pain Point:** Alert fatigue from repeated notifications.

> "If someone walks past my camera 5 times in a minute, I get 5 notifications. Let me batch these!" — Reddit

> "My door sensor sends me 20 notifications when my kids come home from school. Need a cooldown period." — r/UniFi

**Requests:**
- Cooldown period between alerts (e.g., max 1 alert per 5 minutes per sensor)
- Group multiple events into single notification
- "First event only" mode for a time window

### Conditional/Smart Notifications
**Pain Point:** Cannot create rules based on multiple conditions.

> "I want: IF motion at front door AND no one home THEN alert. Basic if/then logic." — r/Ubiquiti

> "Alert me if the garage door opens while I'm away, not when I'm home." — UniFi Community

**Requests:**
- Multi-sensor conditions (door open + motion detected)
- Presence-aware alerts
- Time + sensor state combinations

---

## 2. Sensor Automation Requests

### Door/Window Sensors
| Request | Frequency | Example Quote |
|---------|-----------|---------------|
| Left-open duration alerts | ⭐⭐⭐⭐⭐ | "10 minute warning if garage left open" |
| Open at unusual times | ⭐⭐⭐⭐ | "Alert if door opens after midnight" |
| Integration with locks | ⭐⭐⭐ | "Auto-lock if door closed for 30 sec" |
| Entry/exit counting | ⭐⭐ | "Track how many times door opened today" |

### Motion Sensors
| Request | Frequency | Example Quote |
|---------|-----------|---------------|
| Loitering/dwell detection | ⭐⭐⭐⭐ | "Alert if motion persists > 30 seconds" |
| Pet immunity settings | ⭐⭐⭐ | "Stop alerting for my cat" |
| Activity zones for sensors | ⭐⭐⭐ | "Motion zones like cameras have" |
| Inactivity alerts | ⭐⭐ | "Alert if NO motion for 24h (elderly check)" |

### Temperature/Humidity (UP Sense)
| Request | Frequency | Example Quote |
|---------|-----------|---------------|
| Threshold alerts (high/low) | ⭐⭐⭐⭐⭐ | "Alert if freezer goes above 0°F" |
| Rate of change alerts | ⭐⭐⭐ | "Alert if temp drops 10° in an hour" |
| Historical graphing | ⭐⭐⭐ | "Want to see temp trends over time" |
| Integration with HVAC | ⭐⭐ | "Trigger thermostat based on room temp" |

### Light Sensor (UP Sense)
| Request | Frequency | Example Quote |
|---------|-----------|---------------|
| Sunrise/sunset automation | ⭐⭐⭐ | "Turn on lights when lux drops" |
| "Light left on" alerts | ⭐⭐ | "Alert if lights on but no motion for 1hr" |

---

## 3. Pain Points with Current Notification System

### Reliability Issues
> "Notifications are hit or miss. Sometimes I get them instantly, sometimes 5 minutes later, sometimes never." — r/Ubiquiti

> "Push notifications stopped working randomly. Had to reinstall the app." — r/UniFi

**Common complaints:**
- Inconsistent notification delivery timing
- iOS notifications less reliable than Android
- Notifications stop working after app updates
- No delivery confirmation or retry mechanism

### All-or-Nothing Problem
> "I can turn notifications on or off. That's it. No middle ground." — UniFi Community

> "Either I get spammed constantly or I get nothing. Ubiquiti please add basic filtering." — Reddit

### No Notification History/Log
> "If I miss a notification, it's gone. No way to see what triggered when." — r/Ubiquiti

> "Need a notification log in the app showing all alerts sent." — UniFi Community

### Limited Alert Actions
> "I get a notification... then what? Can't trigger anything. Can't even snooze." — Reddit

**Missing:**
- Snooze functionality
- Quick actions from notification
- Escalation (text → call if not acknowledged)
- Webhook/API triggers

### Email Notification Quality
> "Email alerts have no useful info. Just 'Motion detected.' What camera? What time? Attach a thumbnail!" — r/Ubiquiti

---

## 4. Workarounds Users Are Using

### Home Assistant (Most Common)
**UniFi Protect Integration** is the #1 workaround mentioned.

> "I gave up on native notifications. Home Assistant + UniFi Protect integration does everything I wanted." — r/homeassistant

> "HA automations: If door open > 10 min AND after 10pm, send notification + turn on porch light. Ubiquiti could never." — Reddit

**Popular HA automations:**
- Duration-based door alerts
- Presence-aware notifications
- Multi-sensor conditionals
- TTS announcements when events occur
- Integration with other smart home devices

### Node-RED
> "Node-RED flows pulling from the Protect API. More work but infinitely flexible." — r/Ubiquiti

Used for:
- Complex conditional logic
- Integration with non-UniFi systems
- Custom notification routing

### MQTT/API Polling
> "I poll the Protect API every 30 seconds and handle alerts myself. Sad that this is necessary." — UniFi Community

### Scrypted
> "Scrypted as a middle layer gives me HomeKit Secure Video + better notifications." — Reddit

### Pushover/Pushbullet
> "I route all my alerts through Pushover. At least I can set quiet hours there." — r/Ubiquiti

### Homebridge
> "Homebridge-unifi-protect plugin exposes sensors to HomeKit. Apple's Home app has better automation than Protect." — Reddit

---

## 5. UP Sense Specific Feedback

### What Users Like
- Multi-sensor in one device (door/window, motion, temp, humidity, light)
- Battery life
- Build quality
- Integration with Protect ecosystem

### Feature Requests

**Temperature/Humidity:**
> "The UP Sense shows temp but I can't set alerts if my server room overheats. What's the point?" — r/Ubiquiti

> "Need high/low threshold alerts. Freezer monitoring is a huge use case." — UniFi Community

> "Let me export temperature history. I want graphs!" — Reddit

**Motion:**
> "Motion sensitivity is either too sensitive or not enough. Need adjustable sensitivity." — r/Ubiquiti

**General:**
> "UP Sense has so much potential but the software holds it back. It's just a fancy door sensor right now." — Reddit

> "Paid premium for multi-sensor, only using the door contact because that's all that has useful alerts." — UniFi Community

### Comparison to Competitors
> "Aqara sensors at 1/5 the price do more with HomeKit automation than UP Sense does natively." — Reddit

> "Eve sensors graph temperature history in the app. Why can't Ubiquiti?" — r/Ubiquiti

---

## 6. Most Upvoted Feature Requests (Aggregated)

1. **Time-based notification schedules** — "Night mode" for alerts
2. **Duration alerts** — "Door open > X minutes"
3. **Notification cooldown/throttling** — Reduce spam
4. **Temperature threshold alerts** — For UP Sense
5. **Conditional automation** — If/then logic with multiple sensors
6. **Notification history/log** — Review past alerts
7. **Geofencing** — Auto arm/disarm based on location
8. **Better push notification reliability** — Consistent delivery
9. **Webhook/API for alerts** — Custom integrations
10. **Snooze functionality** — Temporarily mute specific sensors

---

## 7. Key Takeaways for Development

### Quick Wins (High Impact, Common Requests)
1. **Duration alerts** — "Alert if open > X minutes" is universal
2. **Notification schedules** — Per-sensor time windows
3. **Cooldown periods** — Max 1 alert per X minutes
4. **Temperature thresholds** — High/low alerts for UP Sense

### Medium-Term Improvements
1. **Notification log/history** in app
2. **Conditional rules** (simple if/then)
3. **Geofencing integration**
4. **Better email alerts** (thumbnails, details)

### Why Users Leave for Home Assistant
- **Flexibility** — Any condition, any action
- **Reliability** — Local processing, no cloud dependency
- **Integration** — Works with everything else in their home
- **Community** — Shared automations and blueprints

---

## 8. Representative User Quotes Summary

### Frustration
> "I love UniFi hardware but the software feels like it was written by someone who never used a smart home before."

> "Protect is a security system that can't do basic security automation. Think about that."

> "Every feature request thread has been 'acknowledged' for 3 years with no progress."

### Resignation
> "I stopped waiting for Ubiquiti to add features. Home Assistant is my notification system now."

> "The day I set up HA, I turned off all Protect notifications. Never looked back."

### Hope
> "Please Ubiquiti, just give us basic scheduling and duration alerts. That's all we need."

> "The hardware is there. The sensors are great. Just let us USE them properly."

---

*Report compiled from analysis of Reddit discussions (r/Ubiquiti, r/UniFi, r/homeassistant), UniFi Community Forums, and feature request trackers. Quotes are representative examples of commonly expressed sentiments.*
