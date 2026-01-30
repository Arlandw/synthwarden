"""SynthWarden CLI - Command-line interface for setup and management."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.panel import Panel

from .user_config import get_config_manager, UserConfig, UniFiConfig

console = Console()


def run_async(coro):
    """Run async function in sync context."""
    return asyncio.get_event_loop().run_until_complete(coro)


@click.group()
@click.version_option(version="0.1.0", prog_name="synthwarden")
def cli():
    """SynthWarden - Smart notifications for UniFi Protect sensors."""
    pass


# === Setup / Config Commands ===

@cli.command()
def setup():
    """Interactive setup wizard for first-time configuration."""
    console.print(Panel.fit(
        "[bold cyan]SynthWarden Setup Wizard[/]\n"
        "Let's configure your UniFi Protect connection.",
        border_style="cyan"
    ))
    
    manager = get_config_manager()
    config = manager.load()
    
    # UniFi Protect credentials
    console.print("\n[bold]UniFi Protect Connection[/]")
    
    host = Prompt.ask(
        "UniFi Protect IP/hostname",
        default=config.unifi.host or "192.168.1.1"
    )
    
    port = Prompt.ask(
        "Port",
        default=str(config.unifi.port or 443)
    )
    
    username = Prompt.ask(
        "Username",
        default=config.unifi.username or "admin"
    )
    
    password = Prompt.ask(
        "Password",
        password=True
    )
    
    verify_ssl = Confirm.ask(
        "Verify SSL certificate?",
        default=False
    )
    
    # Update config
    config.unifi = UniFiConfig(
        host=host,
        port=int(port),
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )
    
    # Test connection
    console.print("\n[yellow]Testing connection...[/]")
    
    try:
        success = run_async(test_unifi_connection(config.unifi))
        if success:
            console.print("[green]✓ Connection successful![/]")
            config.setup_complete = True
            manager.save(config)
            
            console.print(f"\n[dim]Config saved to: {manager.path}[/]")
            console.print("\n[bold green]Setup complete![/] Run [cyan]synthwarden serve[/] to start.")
        else:
            console.print("[red]✗ Connection failed. Check credentials and try again.[/]")
            if Confirm.ask("Save config anyway?"):
                manager.save(config)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/]")
        if Confirm.ask("Save config anyway?"):
            manager.save(config)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def config(as_json: bool):
    """Show current configuration."""
    manager = get_config_manager()
    
    if not manager.exists():
        console.print("[yellow]No config found. Run 'synthwarden setup' first.[/]")
        return
    
    cfg = manager.load()
    
    if as_json:
        import json
        # Mask password
        data = cfg.model_dump()
        if data["unifi"]["password"]:
            data["unifi"]["password"] = "********"
        console.print(json.dumps(data, indent=2))
        return
    
    # Pretty print
    console.print(Panel.fit("[bold]SynthWarden Configuration[/]", border_style="blue"))
    
    console.print("\n[bold cyan]UniFi Protect[/]")
    console.print(f"  Host: {cfg.unifi.host}:{cfg.unifi.port}")
    console.print(f"  User: {cfg.unifi.username}")
    console.print(f"  Password: {'********' if cfg.unifi.password else '[dim]not set[/]'}")
    console.print(f"  SSL Verify: {cfg.unifi.verify_ssl}")
    
    if cfg.sensors:
        console.print("\n[bold cyan]Sensor Nicknames[/]")
        for sensor_id, sensor_cfg in cfg.sensors.items():
            status = "✓" if sensor_cfg.monitor else "○"
            console.print(f"  {status} {sensor_cfg.name} ({sensor_id[:8]}...)")
    
    console.print(f"\n[bold cyan]Preferences[/]")
    for key, value in cfg.preferences.items():
        console.print(f"  {key}: {value}")
    
    console.print(f"\n[dim]Config file: {manager.path}[/]")


@cli.command()
@click.argument("key")
@click.argument("value")
def set(key: str, value: str):
    """Set a configuration value.
    
    Examples:
        synthwarden set unifi.host 192.168.1.100
        synthwarden set preferences.web_port 8080
    """
    manager = get_config_manager()
    config = manager.load()
    
    parts = key.split(".")
    
    if parts[0] == "unifi" and len(parts) == 2:
        field = parts[1]
        if field == "port":
            value = int(value)
        elif field == "verify_ssl":
            value = value.lower() in ("true", "1", "yes")
        setattr(config.unifi, field, value)
        manager.save()
        console.print(f"[green]✓ Set {key} = {value}[/]")
    
    elif parts[0] == "preferences" and len(parts) == 2:
        field = parts[1]
        # Try to preserve type
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
        config.preferences[field] = value
        manager.save()
        console.print(f"[green]✓ Set {key} = {value}[/]")
    
    else:
        console.print(f"[red]Unknown config key: {key}[/]")
        console.print("Valid keys: unifi.host, unifi.port, unifi.username, unifi.password, unifi.verify_ssl")
        console.print("            preferences.<name>")


# === Sensor Commands ===

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed sensor info")
def sensors(as_json: bool, verbose: bool):
    """List all discovered sensors."""
    manager = get_config_manager()
    config = manager.load()
    
    if not config.unifi.host:
        console.print("[yellow]UniFi not configured. Run 'synthwarden setup' first.[/]")
        return
    
    if not as_json:
        console.print("[yellow]Connecting to UniFi Protect...[/]")
    
    try:
        sensors_list = run_async(discover_sensors(config.unifi))
        
        if as_json:
            import json
            console.print(json.dumps(sensors_list, indent=2, default=str))
            return
        
        if not sensors_list:
            console.print("[yellow]No sensors found.[/]")
            return
        
        table = Table(title="Discovered Sensors")
        table.add_column("Name", style="cyan")
        table.add_column("Model")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Battery")
        if verbose:
            table.add_column("Capabilities")
        table.add_column("ID", style="dim")
        
        for sensor in sensors_list:
            # Check for user nickname
            user_cfg = config.sensors.get(sensor["id"])
            name = user_cfg.name if user_cfg else sensor["name"]
            monitor_icon = "✓ " if (not user_cfg or user_cfg.monitor) else "○ "
            
            battery = f"{sensor['battery']}%" if sensor.get("battery") else "-"
            online_icon = "" if sensor.get("is_online", True) else "⚠️ "
            
            # Color-code state
            state = sensor["state"] or "-"
            if "OPEN" in state:
                state = f"[red]{state}[/]"
            elif "ALARM" in state or "LEAK" in state:
                state = f"[red bold]{state}[/]"
            
            row = [
                monitor_icon + online_icon + name,
                sensor.get("model", "-"),
                sensor["type"],
                state,
                battery,
            ]
            if verbose:
                caps = ", ".join(sensor.get("capabilities", []))
                row.append(caps or "-")
            row.append(sensor["id"][:12] + "...")
            
            table.add_row(*row)
        
        console.print(table)
        
        # Summary by type
        models = {}
        for s in sensors_list:
            m = s.get("model", "unknown")
            models[m] = models.get(m, 0) + 1
        
        summary = " | ".join([f"{v}× {k}" for k, v in models.items()])
        console.print(f"\n[dim]Total: {len(sensors_list)} sensors ({summary})[/]")
        
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


@cli.command()
@click.argument("sensor_id")
@click.argument("name")
def rename(sensor_id: str, name: str):
    """Rename a sensor (set a friendly nickname).
    
    You can use a partial sensor ID (first 8+ chars).
    """
    manager = get_config_manager()
    config = manager.load()
    
    # Find sensor by partial ID
    if len(sensor_id) < 36:
        # Try to find a match
        for sid in config.sensors.keys():
            if sid.startswith(sensor_id):
                sensor_id = sid
                break
    
    manager.set_sensor_name(sensor_id, name)
    console.print(f"[green]✓ Renamed sensor to '{name}'[/]")


@cli.command()
@click.argument("sensor_id")
@click.option("--enable/--disable", default=True, help="Enable or disable monitoring")
def monitor(sensor_id: str, enable: bool):
    """Enable or disable monitoring for a sensor."""
    manager = get_config_manager()
    manager.set_sensor_monitoring(sensor_id, enable)
    
    status = "enabled" if enable else "disabled"
    console.print(f"[green]✓ Monitoring {status} for sensor[/]")


# === Server Commands ===

@cli.command()
@click.option("--port", "-p", default=None, type=int, help="Port to run on")
@click.option("--host", "-h", default="0.0.0.0", help="Host to bind to")
def serve(port: int, host: str):
    """Start the SynthWarden web server."""
    manager = get_config_manager()
    config = manager.load()
    
    if not config.setup_complete and not config.unifi.host:
        console.print("[yellow]First-time setup required.[/]")
        console.print("Run [cyan]synthwarden setup[/] or visit the web UI to configure.")
    
    # Use configured port or default
    if port is None:
        port = config.preferences.get("web_port", 8099)
    
    console.print(f"\n[bold cyan]Starting SynthWarden[/]")
    console.print(f"  Web UI: http://localhost:{port}")
    console.print(f"  API: http://localhost:{port}/api")
    console.print("\n[dim]Press Ctrl+C to stop[/]\n")
    
    import uvicorn
    from .main import app
    
    uvicorn.run(app, host=host, port=port, log_level="info")


@cli.command()
def test():
    """Test connection to UniFi Protect."""
    manager = get_config_manager()
    config = manager.load()
    
    if not config.unifi.host:
        console.print("[yellow]UniFi not configured. Run 'synthwarden setup' first.[/]")
        return
    
    console.print(f"[yellow]Testing connection to {config.unifi.host}...[/]")
    
    try:
        success = run_async(test_unifi_connection(config.unifi))
        if success:
            console.print("[green]✓ Connection successful![/]")
        else:
            console.print("[red]✗ Connection failed[/]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/]")


# === Helper Functions ===

async def test_unifi_connection(unifi_config: UniFiConfig) -> bool:
    """Test UniFi Protect connection."""
    from uiprotect import ProtectApiClient
    
    try:
        client = ProtectApiClient(
            host=unifi_config.host,
            port=unifi_config.port,
            username=unifi_config.username,
            password=unifi_config.password,
            verify_ssl=unifi_config.verify_ssl,
        )
        await asyncio.wait_for(client.update(), timeout=15)
        sensor_count = len(client.bootstrap.sensors)
        console.print(f"[dim]Found {sensor_count} sensors[/]")
        return True
    except asyncio.TimeoutError:
        console.print("[red]Connection timed out[/]")
        return False
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")
        return False


async def discover_sensors(unifi_config: UniFiConfig) -> list[dict]:
    """Discover sensors from UniFi Protect."""
    from uiprotect import ProtectApiClient
    from .sensor_types import parse_sensor, get_sensor_type_display, format_sensor_summary
    
    client = ProtectApiClient(
        host=unifi_config.host,
        port=unifi_config.port,
        username=unifi_config.username,
        password=unifi_config.password,
        verify_ssl=unifi_config.verify_ssl,
    )
    
    await asyncio.wait_for(client.update(), timeout=15)
    
    sensors = []
    for sensor_id, sensor in client.bootstrap.sensors.items():
        state = parse_sensor(sensor)
        
        sensors.append({
            "id": sensor_id,
            "name": sensor.name,
            "model": state.model.value,
            "type": get_sensor_type_display(state.model, state.mount_type),
            "state": format_sensor_summary(state),
            "capabilities": [c.value for c in state.capabilities],
            "battery": state.battery_percent,
            "is_online": state.is_online,
            # Raw values for rules
            "is_open": state.is_open,
            "temperature_c": state.temperature.value if state.temperature else None,
            "humidity": state.humidity.value if state.humidity else None,
            "light_lux": state.light.value if state.light else None,
        })
    
    return sensors


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
