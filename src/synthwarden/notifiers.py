"""Notification dispatchers for Discord, Telegram, Email, OpenClaw."""

import logging
from datetime import datetime
import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


async def send_notification(
    channel_type: str,
    channel_config: dict,
    rule_name: str,
    sensor_name: str,
    state: str,
) -> bool:
    """Send notification to the specified channel."""
    
    if channel_type == "discord":
        return await send_discord(channel_config, rule_name, sensor_name, state)
    elif channel_type == "telegram":
        return await send_telegram(channel_config, rule_name, sensor_name, state)
    elif channel_type == "email":
        return await send_email(channel_config, rule_name, sensor_name, state)
    elif channel_type == "openclaw":
        return await send_openclaw(channel_config, rule_name, sensor_name, state)
    else:
        logger.warning(f"Unknown channel type: {channel_type}")
        return False


async def send_discord(
    config: dict,
    rule_name: str,
    sensor_name: str,
    state: str,
) -> bool:
    """Send Discord webhook notification."""
    webhook_url = config.get("webhook_url")
    if not webhook_url:
        logger.error("Discord webhook URL not configured")
        return False
    
    now = datetime.now().strftime("%I:%M %p")
    
    embed = {
        "title": "🚨 SynthWarden Alert",
        "description": f"**{sensor_name}** is {state}",
        "color": 0xFF4444,  # Red
        "fields": [
            {"name": "📍 Sensor", "value": sensor_name, "inline": True},
            {"name": "🕐 Time", "value": now, "inline": True},
            {"name": "📋 Rule", "value": rule_name, "inline": False},
        ],
        "footer": {"text": "SynthWarden"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    payload = {"embeds": [embed]}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    logger.info(f"Discord notification sent: {sensor_name}")
                    return True
                else:
                    logger.error(f"Discord webhook failed: {resp.status}")
                    return False
    except Exception as e:
        logger.error(f"Discord notification error: {e}")
        return False


async def send_telegram(
    config: dict,
    rule_name: str,
    sensor_name: str,
    state: str,
) -> bool:
    """Send Telegram bot notification."""
    bot_token = config.get("bot_token")
    chat_id = config.get("chat_id")
    
    if not bot_token or not chat_id:
        logger.error("Telegram bot_token or chat_id not configured")
        return False
    
    now = datetime.now().strftime("%I:%M %p")
    
    message = f"""🚨 *SynthWarden Alert*

*{sensor_name}* is {state}

📍 Sensor: {sensor_name}
🕐 Time: {now}
📋 Rule: {rule_name}"""
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    logger.info(f"Telegram notification sent: {sensor_name}")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"Telegram failed: {resp.status} - {body}")
                    return False
    except Exception as e:
        logger.error(f"Telegram notification error: {e}")
        return False


async def send_email(
    config: dict,
    rule_name: str,
    sensor_name: str,
    state: str,
) -> bool:
    """Send email notification via SMTP."""
    smtp_host = config.get("smtp_host")
    smtp_port = config.get("smtp_port", 587)
    smtp_user = config.get("smtp_user")
    smtp_pass = config.get("smtp_pass")
    to_address = config.get("to_address")
    
    if not all([smtp_host, smtp_user, smtp_pass, to_address]):
        logger.error("Email SMTP configuration incomplete")
        return False
    
    now = datetime.now().strftime("%I:%M %p")
    
    subject = f"🚨 SynthWarden: {sensor_name} {state}"
    
    body = f"""
    <html>
    <body>
    <h2>🚨 SynthWarden Alert</h2>
    <p><strong>{sensor_name}</strong> is {state}</p>
    <table>
        <tr><td>📍 Sensor:</td><td>{sensor_name}</td></tr>
        <tr><td>🕐 Time:</td><td>{now}</td></tr>
        <tr><td>📋 Rule:</td><td>{rule_name}</td></tr>
    </table>
    </body>
    </html>
    """
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(body, "html"))
    
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logger.info(f"Email notification sent: {sensor_name}")
        return True
    except Exception as e:
        logger.error(f"Email notification error: {e}")
        return False


async def send_openclaw(
    config: dict,
    rule_name: str,
    sensor_name: str,
    state: str,
) -> bool:
    """Send notification via OpenClaw gateway to Discord/Telegram/etc."""
    gateway_url = config.get("gateway_url", "").rstrip("/")
    gateway_token = config.get("gateway_token", "")
    target = config.get("target", "")  # e.g., "user:130447280661594112" or channel ID
    
    if not gateway_url or not target:
        logger.error("OpenClaw gateway_url and target are required")
        return False
    
    now = datetime.now().strftime("%I:%M %p")
    
    # Format message for Discord/chat
    message = f"🚨 **SynthWarden Alert**\n\n**{sensor_name}** is {state}\n\n📍 Sensor: {sensor_name}\n🕐 Time: {now}\n📋 Rule: {rule_name}"
    
    # OpenClaw gateway message endpoint
    url = f"{gateway_url}/api/message"
    
    payload = {
        "action": "send",
        "target": target,
        "message": message,
    }
    
    headers = {"Content-Type": "application/json"}
    if gateway_token:
        headers["Authorization"] = f"Bearer {gateway_token}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status in (200, 201, 204):
                    logger.info(f"OpenClaw notification sent: {sensor_name}")
                    return True
                else:
                    body = await resp.text()
                    logger.error(f"OpenClaw failed: {resp.status} - {body}")
                    return False
    except Exception as e:
        logger.error(f"OpenClaw notification error: {e}")
        return False
