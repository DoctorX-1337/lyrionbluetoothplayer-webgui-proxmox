import asyncio
import json
import math
import struct
import tempfile
import wave
from pathlib import Path
from app.errors import PlayerError
from app.process import command


class AudioManager:
    def __init__(self, settings):
        self.settings = settings

    async def list(self, kind):
        return json.loads(await command("pactl", "--format=json", "list", kind))

    async def sink_for(self, mac):
        for sink in await self.list("sinks"):
            props = sink.get("properties", {})
            if props.get("api.bluez5.address", "").upper() == mac or mac.replace(":", "_") in sink.get("name", "").upper():
                if "a2dp" in props.get("api.bluez5.profile", "a2dp").lower():
                    return sink
        return None

    async def activate_profile(self, mac, codec="auto"):
        for card in await self.list("cards"):
            props = card.get("properties", {})
            if props.get("api.bluez5.address", "").upper() != mac and mac.replace(":", "_") not in card.get("name", "").upper():
                continue
            profiles = card.get("profiles", {})
            entries = list(profiles.values()) if isinstance(profiles, dict) else profiles
            # pactl JSON on some versions uses keys for profile names.
            if isinstance(profiles, dict):
                entries = [{**v, "name": k} for k, v in profiles.items()]
            a2dp = [p for p in entries if p.get("name", "").startswith("a2dp") and p.get("available") not in ("no", False)]
            if not a2dp:
                raise PlayerError("Für diesen Lautsprecher ist kein A2DP-Profil verfügbar.", "no_a2dp")
            preferred = next((p for p in a2dp if codec != "auto" and codec.replace("_", "-") in p["name"]), None)
            selected = preferred or next((p for p in a2dp if "sbc" in p["name"]), a2dp[0])
            active = card.get("active_profile", "")
            if isinstance(active, dict):
                active = active.get("name")
            if codec == "auto" and any(p["name"] == active for p in a2dp):
                return
            if active != selected["name"]:
                await command("pactl", "set-card-profile", str(card["index"]), selected["name"])
            return
        raise PlayerError("Bluetooth-Audiokarte ist noch nicht verfügbar.", "waiting_a2dp")

    async def select(self, mac, volume, codec="auto"):
        deadline = asyncio.get_running_loop().time() + self.settings.connect_timeout
        last_error = PlayerError("Kein A2DP-Sink verfügbar. Prüfen Sie PipeWire, WirePlumber und den Lautsprecher.", "no_sink")
        while asyncio.get_running_loop().time() < deadline:
            try:
                await self.activate_profile(mac, codec)
                sink = await self.sink_for(mac)
                if sink:
                    await command("pactl", "set-default-sink", sink["name"])
                    await self.volume(volume, sink["name"])
                    for stream in await self.list("sink-inputs"):
                        await command("pactl", "move-sink-input", str(stream["index"]), sink["name"])
                    return sink
            except PlayerError as exc:
                last_error = exc
            await asyncio.sleep(1)
        raise last_error

    async def volume(self, value, sink="@DEFAULT_SINK@"):
        value = min(value, self.settings.max_volume)
        await command("pactl", "set-sink-volume", sink, f"{value}%")
        return value

    async def status(self):
        try:
            default = (await command("pactl", "get-default-sink")).strip()
            sinks = await self.list("sinks")
            sink = next((s for s in sinks if s["name"] == default), None)
            # PipeWire's idle dummy sink is not an available physical output.
            if sink and sink.get("name") == "auto_null":
                sink = None
            volume = None
            codec = None
            if sink:
                channels = sink.get("volume", {}).values()
                values = [v.get("value", 0) / 65536 * 100 for v in channels]
                volume = round(sum(values) / len(values)) if values else None
                codec = sink.get("properties", {}).get("api.bluez5.codec")
            return {"available": True, "sink": default if sink else None, "volume": volume,
                    "codec": codec, "a2dp": bool(sink and "bluez" in default),
                    "playing": bool(sink and sink.get("state") == "RUNNING"), "sinks": [{"name": s["name"], "description": s.get("description"), "state": s.get("state")} for s in sinks if s.get("name") != "auto_null"]}
        except (PlayerError, ValueError, TimeoutError):
            return {"available": False, "sink": None, "volume": None, "codec": None, "a2dp": False, "playing": False, "sinks": []}

    async def test(self, mac):
        sink = await self.sink_for(mac)
        if not sink:
            raise PlayerError("Verbinden Sie den Lautsprecher vor dem Testton.", "no_sink")
        with tempfile.TemporaryDirectory(prefix="lyrion-tone-") as directory:
            path = Path(directory) / "tone.wav"
            rate, duration = 48000, 1.5
            with wave.open(str(path), "wb") as wav:
                wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
                samples = bytearray()
                for n in range(int(rate * duration)):
                    envelope = min(1, n / (rate * .05), (rate * duration - n) / (rate * .1))
                    samples.extend(struct.pack("<h", int(3200 * envelope * math.sin(2 * math.pi * 440 * n / rate))))
                wav.writeframes(samples)
            await command("paplay", "--device", sink["name"], "--volume=22000", str(path), timeout=8)
