#!/usr/bin/env python3
"""
Agent Presentation Protocol (APP) — Home Assistant Bridge

Bridges Home Assistant entities to an APP relay, allowing natural
language control of your smart home through any paired APP surface.

This runs as a standalone script alongside Home Assistant. It connects
to both the HA WebSocket API and an APP relay, translating between
device_action messages and HA service calls.

DISCLAIMER: This code is provided as-is for reference only.
See the top-level README for the full disclaimer.

Usage:
  pip install websockets aiohttp
  export BRIDGE_TOKEN="your_token"
  export HA_URL="http://homeassistant.local:8123"
  export HA_TOKEN="your_long_lived_access_token"
  python chitin_ha_bridge.py
"""

import asyncio
import json
import os
import time
import uuid
import logging
from typing import Optional

try:
    import websockets
except ImportError:
    print("Install: pip install websockets")
    exit(1)

try:
    import aiohttp
except ImportError:
    print("Install: pip install aiohttp")
    exit(1)

# ============================================================
# CONFIGURATION
# ============================================================

BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "YOUR_BRIDGE_TOKEN")
RELAY_URL = os.environ.get("APP_RELAY_URL", "wss://your-relay.example/ws/bridge")

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "YOUR_HA_LONG_LIVED_TOKEN")

# Which entity domains to expose via APP
EXPOSED_DOMAINS = [
    "light",
    "switch",
    "fan",
    "lock",
    "cover",       # blinds, shades, garage doors
    "climate",     # thermostats
    "media_player",
    "scene",
    "script",
    "vacuum",
    "input_boolean",
]

# Conservative cap for headless intelligence prompt size; tune to your target relay's capacity.
MAX_ENTITIES = 40

SENSOR_INTERVAL = 60  # Report entity states every 60s
HEARTBEAT_INTERVAL = 25
RECONNECT_INITIAL = 1
RECONNECT_MAX = 60

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chitin-ha-bridge")

# ============================================================
# Home Assistant API client
# ============================================================


class HomeAssistantClient:
    """Simple REST API client for Home Assistant."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.session: Optional[aiohttp.ClientSession] = None
        self.entities: dict = {}  # entity_id → state dict

    async def start(self):
        self.session = aiohttp.ClientSession(headers=self.headers)

    async def stop(self):
        if self.session:
            await self.session.close()

    async def get_states(self) -> list:
        """Fetch all entity states from HA."""
        async with self.session.get(f"{self.base_url}/api/states") as resp:
            if resp.status == 200:
                states = await resp.json()
                self.entities = {s["entity_id"]: s for s in states}
                return states
            else:
                log.error("Failed to fetch states: %d", resp.status)
                return []

    async def call_service(self, domain: str, service: str, entity_id: str,
                           data: dict = None) -> bool:
        """Call a Home Assistant service."""
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)

        url = f"{self.base_url}/api/services/{domain}/{service}"
        log.info("Calling HA service: %s/%s → %s %s", domain, service, entity_id, data or "")

        async with self.session.post(url, json=payload) as resp:
            if resp.status in (200, 201):
                return True
            else:
                body = await resp.text()
                log.error("HA service call failed (%d): %s", resp.status, body)
                return False

    def get_exposed_entities(self) -> list:
        """Return entities in exposed domains, sorted by domain and name."""
        exposed = []
        for eid, state in self.entities.items():
            domain = eid.split(".")[0]
            if domain in EXPOSED_DOMAINS:
                exposed.append(state)
        exposed.sort(key=lambda s: s["entity_id"])
        return exposed[:MAX_ENTITIES]


# ============================================================
# Agent Card builder
# ============================================================


def build_agent_card(ha: HomeAssistantClient) -> dict:
    """Build an APP Agent Card from HA entity states."""
    entities = ha.get_exposed_entities()

    # Build status from current entity states
    status = {}
    for entity in entities:
        eid = entity["entity_id"]
        friendly = entity.get("attributes", {}).get("friendly_name", eid)
        state = entity["state"]
        status[friendly] = state

    # Build available actions from entity domains
    actions = []

    # Group entities by domain for action generation
    by_domain = {}
    for entity in entities:
        domain = entity["entity_id"].split(".")[0]
        by_domain.setdefault(domain, []).append(entity)

    for domain, domain_entities in by_domain.items():
        entity_names = []
        for e in domain_entities:
            name = e.get("attributes", {}).get("friendly_name", e["entity_id"])
            entity_names.append(name)

        if domain == "light":
            actions.append({
                "id": f"light_turn_on",
                "name": "Turn On Light",
                "description": f"Turn on a light. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "brightness_pct",
                        "type": "integer",
                        "required": False,
                        "min": 1,
                        "max": 100,
                    },
                ],
            })
            actions.append({
                "id": f"light_turn_off",
                "name": "Turn Off Light",
                "description": f"Turn off a light. Available: {', '.join(entity_names)}",
                "params": [{
                    "name": "entity_name",
                    "type": "string",
                    "required": True,
                    "options": entity_names,
                }],
            })

        elif domain == "switch":
            actions.append({
                "id": "switch_toggle",
                "name": "Toggle Switch",
                "description": f"Turn a switch on or off. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "state",
                        "type": "string",
                        "required": True,
                        "options": ["on", "off", "toggle"],
                    },
                ],
            })

        elif domain == "climate":
            actions.append({
                "id": "climate_set_temperature",
                "name": "Set Temperature",
                "description": f"Set thermostat temperature. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "temperature",
                        "type": "number",
                        "required": True,
                        "min": 50,
                        "max": 90,
                    },
                ],
            })
            actions.append({
                "id": "climate_set_mode",
                "name": "Set HVAC Mode",
                "description": f"Set thermostat mode. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "mode",
                        "type": "string",
                        "required": True,
                        "options": ["heat", "cool", "auto", "off"],
                    },
                ],
            })

        elif domain == "lock":
            actions.append({
                "id": "lock_control",
                "name": "Lock/Unlock",
                "description": f"Lock or unlock. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "action",
                        "type": "string",
                        "required": True,
                        "options": ["lock", "unlock"],
                    },
                ],
            })

        elif domain == "cover":
            actions.append({
                "id": "cover_control",
                "name": "Open/Close Cover",
                "description": f"Control blinds, shades, or garage doors. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "action",
                        "type": "string",
                        "required": True,
                        "options": ["open", "close", "stop"],
                    },
                ],
            })

        elif domain == "fan":
            actions.append({
                "id": "fan_control",
                "name": "Fan Control",
                "description": f"Turn fan on/off or set speed. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "action",
                        "type": "string",
                        "required": True,
                        "options": ["on", "off"],
                    },
                ],
            })

        elif domain == "scene":
            actions.append({
                "id": "scene_activate",
                "name": "Activate Scene",
                "description": f"Activate a scene. Available: {', '.join(entity_names)}",
                "params": [{
                    "name": "entity_name",
                    "type": "string",
                    "required": True,
                    "options": entity_names,
                }],
            })

        elif domain == "media_player":
            actions.append({
                "id": "media_control",
                "name": "Media Control",
                "description": f"Control media playback. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "action",
                        "type": "string",
                        "required": True,
                        "options": ["play", "pause", "stop", "next", "previous", "volume_up", "volume_down"],
                    },
                ],
            })

        elif domain == "vacuum":
            actions.append({
                "id": "vacuum_control",
                "name": "Vacuum Control",
                "description": f"Control robot vacuum. Available: {', '.join(entity_names)}",
                "params": [
                    {
                        "name": "entity_name",
                        "type": "string",
                        "required": True,
                        "options": entity_names,
                    },
                    {
                        "name": "action",
                        "type": "string",
                        "required": True,
                        "options": ["start", "stop", "return_to_base", "locate"],
                    },
                ],
            })

    # Read all states action
    actions.append({
        "id": "read_states",
        "name": "Read All States",
        "description": "Get the current state of all exposed entities",
    })

    card = {
        "protocol_version": "0.4",
        "agent": {
            "name": "Home Assistant",
            "version": "1.0.0",
            "description": f"Home Assistant bridge with {len(entities)} entities across {len(by_domain)} domains",
        },
        "device": {
            "type": "smart_home_hub",
            "manufacturer": "Home Assistant",
            "model": "Core",
            "interaction_model": "headless",
            "status": status,
            "available_actions": actions,
        },
        # Headless device: interaction_model="headless" plus omitted
        # input_accepts/output_modalities declares no direct human I/O.
        "capabilities": {
            "streaming": False,
            "emotions": [],
        },
    }
    return {"type": "agent_card", "card": card}


def build_sensor_event(ha: HomeAssistantClient, trigger: str = "periodic") -> dict:
    """Build sensor event with current entity states."""
    entities = ha.get_exposed_entities()
    status = {}
    for entity in entities:
        friendly = entity.get("attributes", {}).get("friendly_name", entity["entity_id"])
        status[friendly] = entity["state"]

    return {
        "type": "sensor_event",
        "id": str(uuid.uuid4()),
        "sensor": "smart_home",
        "value": status,
        "trigger": trigger,
        "timestamp": int(time.time() * 1000),
    }


# ============================================================
# Entity name → entity_id resolution
# ============================================================


def resolve_entity(ha: HomeAssistantClient, friendly_name: str, domain: str = None) -> Optional[str]:
    """Find entity_id by friendly name, optionally filtered by domain."""
    name_lower = friendly_name.lower().strip()
    for eid, state in ha.entities.items():
        if domain and not eid.startswith(f"{domain}."):
            continue
        fn = state.get("attributes", {}).get("friendly_name", "")
        if fn.lower() == name_lower:
            return eid
    # Fuzzy fallback: check if name is contained
    for eid, state in ha.entities.items():
        if domain and not eid.startswith(f"{domain}."):
            continue
        fn = state.get("attributes", {}).get("friendly_name", "")
        if name_lower in fn.lower() or fn.lower() in name_lower:
            return eid
    return None


# ============================================================
# Action handlers
# ============================================================


async def handle_action(ws, ha: HomeAssistantClient, action: str, params: dict):
    log.info("Action: %s %s", action, params)
    entity_name = params.get("entity_name", "")

    if action == "light_turn_on":
        eid = resolve_entity(ha, entity_name, "light")
        if eid:
            svc_data = {}
            if "brightness_pct" in params:
                svc_data["brightness_pct"] = params["brightness_pct"]
            await ha.call_service("light", "turn_on", eid, svc_data or None)
        else:
            await send_error(ws, f"Light not found: {entity_name}")

    elif action == "light_turn_off":
        eid = resolve_entity(ha, entity_name, "light")
        if eid:
            await ha.call_service("light", "turn_off", eid)
        else:
            await send_error(ws, f"Light not found: {entity_name}")

    elif action == "switch_toggle":
        eid = resolve_entity(ha, entity_name, "switch")
        if eid:
            state = params.get("state", "toggle")
            service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(state, "toggle")
            await ha.call_service("switch", service, eid)
        else:
            await send_error(ws, f"Switch not found: {entity_name}")

    elif action == "climate_set_temperature":
        eid = resolve_entity(ha, entity_name, "climate")
        if eid:
            await ha.call_service("climate", "set_temperature", eid, {
                "temperature": params.get("temperature", 72),
            })
        else:
            await send_error(ws, f"Thermostat not found: {entity_name}")

    elif action == "climate_set_mode":
        eid = resolve_entity(ha, entity_name, "climate")
        if eid:
            await ha.call_service("climate", "set_hvac_mode", eid, {
                "hvac_mode": params.get("mode", "auto"),
            })
        else:
            await send_error(ws, f"Thermostat not found: {entity_name}")

    elif action == "lock_control":
        eid = resolve_entity(ha, entity_name, "lock")
        if eid:
            action = params.get("action", "lock")
            await ha.call_service("lock", action, eid)
        else:
            await send_error(ws, f"Lock not found: {entity_name}")

    elif action == "cover_control":
        eid = resolve_entity(ha, entity_name, "cover")
        if eid:
            action = params.get("action", "stop")
            service = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}.get(action, "stop_cover")
            await ha.call_service("cover", service, eid)
        else:
            await send_error(ws, f"Cover not found: {entity_name}")

    elif action == "fan_control":
        eid = resolve_entity(ha, entity_name, "fan")
        if eid:
            action = params.get("action", "on")
            service = "turn_on" if action == "on" else "turn_off"
            await ha.call_service("fan", service, eid)
        else:
            await send_error(ws, f"Fan not found: {entity_name}")

    elif action == "scene_activate":
        eid = resolve_entity(ha, entity_name, "scene")
        if eid:
            await ha.call_service("scene", "turn_on", eid)
        else:
            await send_error(ws, f"Scene not found: {entity_name}")

    elif action == "media_control":
        eid = resolve_entity(ha, entity_name, "media_player")
        if eid:
            action = params.get("action", "play")
            service_map = {
                "play": "media_play",
                "pause": "media_pause",
                "stop": "media_stop",
                "next": "media_next_track",
                "previous": "media_previous_track",
                "volume_up": "volume_up",
                "volume_down": "volume_down",
            }
            service = service_map.get(action, "media_play")
            await ha.call_service("media_player", service, eid)
        else:
            await send_error(ws, f"Media player not found: {entity_name}")

    elif action == "vacuum_control":
        eid = resolve_entity(ha, entity_name, "vacuum")
        if eid:
            action = params.get("action", "start")
            await ha.call_service("vacuum", action, eid)
        else:
            await send_error(ws, f"Vacuum not found: {entity_name}")

    elif action == "read_states":
        await ha.get_states()

    else:
        await send_error(ws, f"Unknown action: {action}")
        return

    # Refresh states and report
    await ha.get_states()
    await ws.send(json.dumps(build_sensor_event(ha, trigger="event")))


async def send_error(ws, message: str):
    await ws.send(json.dumps({
        "type": "error",
        "code": "action_failed",
        "message": message,
    }))


# ============================================================
# Main bridge loop
# ============================================================


async def bridge_loop():
    ha = HomeAssistantClient(HA_URL, HA_TOKEN)
    await ha.start()

    # Initial state fetch
    log.info("Fetching Home Assistant states...")
    await ha.get_states()
    entities = ha.get_exposed_entities()
    log.info("Found %d exposed entities across %d total",
             len(entities), len(ha.entities))

    reconnect_delay = RECONNECT_INITIAL
    url = f"{RELAY_URL}?token={BRIDGE_TOKEN}"

    try:
        while True:
            try:
                log.info("Connecting to relay...")
                async with websockets.connect(url, ping_interval=HEARTBEAT_INTERVAL) as ws:
                    log.info("Connected to relay")
                    reconnect_delay = RECONNECT_INITIAL

                    # Refresh states and send Agent Card
                    await ha.get_states()
                    card = build_agent_card(ha)
                    await ws.send(json.dumps(card))
                    log.info("Agent Card sent (%d actions)", len(card["device"]["available_actions"]))

                    await ws.send(json.dumps(build_sensor_event(ha)))

                    await asyncio.gather(
                        message_handler(ws, ha),
                        sensor_reporter(ws, ha),
                    )

            except websockets.ConnectionClosed as e:
                log.warning("Connection closed: %s", e)
            except Exception as e:
                log.error("Error: %s", e)

            log.info("Reconnecting in %ds...", reconnect_delay)
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX)
    finally:
        await ha.stop()


async def message_handler(ws, ha: HomeAssistantClient):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if msg.get("type") == "device_action":
            await handle_action(
                ws, ha,
                msg.get("action", ""),
                msg.get("parameters", {}),
            )


async def sensor_reporter(ws, ha: HomeAssistantClient):
    while True:
        await asyncio.sleep(SENSOR_INTERVAL)
        try:
            await ha.get_states()
            await ws.send(json.dumps(build_sensor_event(ha)))
            log.debug("Sensor event sent")
        except Exception:
            break


# ============================================================
# Entry point
# ============================================================


def main():
    log.info("=== APP — Home Assistant Bridge ===")

    if BRIDGE_TOKEN == "YOUR_BRIDGE_TOKEN":
        log.error("Set BRIDGE_TOKEN environment variable")
        return
    if HA_TOKEN == "YOUR_HA_LONG_LIVED_TOKEN":
        log.error("Set HA_TOKEN environment variable (create at HA → Profile → Long-Lived Access Tokens)")
        return

    try:
        asyncio.run(bridge_loop())
    except KeyboardInterrupt:
        log.info("Shutting down...")


if __name__ == "__main__":
    main()
