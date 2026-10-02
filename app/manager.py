import asyncio
import logging
import time
from app.audio import AudioManager
from app.bluetooth import BluetoothManager
from app.database import DeviceRepository
from app.errors import PlayerError
from app.lyrion import LyrionManager
from app.system import SystemManager

log = logging.getLogger("application")
RETRY_DELAYS = (5, 10, 20, 30, 60)


class PlayerManager:
    def __init__(self, config, bluetooth=None, audio=None, lyrion=None, system=None):
        self.config = config
        self.repo = DeviceRepository(config.database)
        self.settings = self.repo.settings(config.defaults)
        self.bluetooth = bluetooth or BluetoothManager(self.settings)
        self.audio = audio or AudioManager(self.settings)
        self.lyrion = lyrion or LyrionManager(self.settings)
        self.system = system or SystemManager()
        self.lock = asyncio.Lock()
        self.snapshot = {}
        self.subscribers = set()
        self.task = None
        self.attempt = 0
        self.next_retry = 0
        self.last_error = ""
        self.reconnect_state = "idle"
        self.manually_disconnected = set()

    async def start(self):
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.lyrion.stop()
        await self.bluetooth.close()
        self.repo.close()

    def record(self, kind, message, mac=None):
        self.repo.event(kind, message, mac)
        logging.getLogger("bluetooth" if kind.startswith("bluetooth") else "audio" if kind.startswith("audio") else "application").info(message)

    async def collect(self):
        async def bt_status():
            try:
                return await self.bluetooth.status()
            except PlayerError as exc:
                return {"adapter": None, "adapters": [], "devices": [], "scanning": False, "error": str(exc)}
        bt, audio, lyrion, system, services = await asyncio.gather(bt_status(), self.audio.status(), self.lyrion.status(), self.system.status(), self.system.services())
        saved = {d["mac_address"]: d for d in self.repo.devices()}
        visible = {d["mac_address"]: d for d in bt["devices"]}
        devices = []
        for mac in sorted(saved.keys() | visible.keys()):
            devices.append({"mac_address": mac, "bluetooth_name": "Unbekannt", "friendly_name": "", "is_default": False,
                "paired": False, "trusted": False, "connected": False, "battery": None, "rssi": None,
                **saved.get(mac, {}), **visible.get(mac, {}), "available": mac in visible})
        bt["devices"] = devices
        pending = self.bluetooth.agent.pending()
        result = {"bluetooth": bt, "audio": audio, "lyrion": lyrion, "system": system, "services": services,
                  "settings": self.settings.model_dump(), "pairing": pending, "pair_results": self.bluetooth.pair_results,
                  "reconnect": {"state": self.reconnect_state, "attempt": self.attempt, "next_retry": self.next_retry, "error": self.last_error},
                  "events": self.repo.events(), "version": "1.0.0"}
        self.snapshot = result
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(result)
        return result

    async def loop(self):
        while True:
            try:
                await self.collect()
                await self.reconnect_step()
            except asyncio.CancelledError:
                raise
            except (PlayerError, TimeoutError, OSError, ValueError) as exc:
                self.last_error = str(exc) if isinstance(exc, PlayerError) else "Statusprüfung fehlgeschlagen. Prüfen Sie die Diagnose."
                log.warning(self.last_error)
            await asyncio.sleep(3)

    async def reconnect_step(self):
        default = self.repo.default()
        if not default or not self.settings.auto_reconnect or not default["auto_connect"] or default["mac_address"] in self.manually_disconnected:
            self.reconnect_state = "idle"
            return
        if self.lock.locked() or time.time() < self.next_retry:
            return
        mac = default["mac_address"]
        current = next((d for d in self.snapshot.get("bluetooth", {}).get("devices", []) if d["mac_address"] == mac), {})
        sink = await self.audio.sink_for(mac) if current.get("connected") else None
        audio = self.snapshot.get("audio", {})
        if current.get("connected") and sink and audio.get("sink") == sink["name"]:
            try:
                await self.lyrion.start()
                self.attempt, self.next_retry = 0, 0
                self.reconnect_state, self.last_error = "connected", ""
                return
            except PlayerError:
                pass
        async with self.lock:
            self.reconnect_state = "connecting"
            try:
                await self.bluetooth.connect(mac)
                await self.audio.select(mac, default["preferred_volume"], self.preferred_codec(default))
                await self.lyrion.start()
                self.record("bluetooth.reconnected", "Standardlautsprecher verbunden; Audio-Routing wiederhergestellt.", mac)
                self.attempt, self.next_retry = 0, 0
                self.reconnect_state, self.last_error = "connected", ""
            except (PlayerError, TimeoutError):
                delay = RETRY_DELAYS[min(self.attempt, len(RETRY_DELAYS) - 1)]
                self.attempt += 1
                self.next_retry = time.time() + delay
                self.reconnect_state = "waiting"
                self.last_error = "Verbindung wird wiederhergestellt. Prüfen Sie, ob der Standardlautsprecher eingeschaltet ist."
                self.record("bluetooth.retry", f"Reconnect-Versuch {self.attempt}; nächster Versuch in {delay} Sekunden.", mac)

    def preferred_codec(self, device):
        preference = device.get("preferred_codec", "auto")
        return self.settings.codec_preference if preference == "auto" else preference

    async def paired(self, mac):
        state = await self.bluetooth.status()
        device = next((d for d in state["devices"] if d["mac_address"] == mac), {})
        self.repo.remember(mac, device.get("bluetooth_name", ""), preferred_volume=self.settings.start_volume)
        self.record("bluetooth.paired", "Bluetooth-Lautsprecher gekoppelt und als vertrauenswürdig gespeichert.", mac)

    async def select_default(self, mac):
        async with self.lock:
            device = self.repo.get(mac)
            if not device:
                raise PlayerError("Koppeln oder speichern Sie zuerst diesen Lautsprecher.", "not_found")
            previous = self.repo.default()
            was_playing = (await self.lyrion.status()).get("mode") == "play"
            if was_playing:
                await self.lyrion.control("pause")
            try:
                await self.bluetooth.connect(mac)
                await self.audio.select(mac, device["preferred_volume"], self.preferred_codec(device))
                await self.lyrion.start()
                self.repo.set_default(mac)
            except (PlayerError, TimeoutError):
                if previous:
                    try:
                        await self.bluetooth.connect(previous["mac_address"])
                        await self.audio.select(previous["mac_address"], previous["preferred_volume"], self.preferred_codec(previous))
                    except (PlayerError, TimeoutError):
                        self.last_error = "Gerätewechsel fehlgeschlagen; bisherige Ausgabe konnte noch nicht wiederhergestellt werden."
                if was_playing:
                    try:
                        await self.lyrion.control("play")
                    except PlayerError:
                        pass
                raise
            self.manually_disconnected.discard(mac)
            self.attempt, self.next_retry = 0, 0
            self.reconnect_state = "connected"
            if previous and previous["mac_address"] != mac:
                try:
                    await self.bluetooth.disconnect(previous["mac_address"])
                except PlayerError:
                    self.record("bluetooth.warning", "Bisheriger Lautsprecher konnte nicht getrennt werden.", previous["mac_address"])
            if was_playing:
                await self.lyrion.control("play")
            self.record("audio.default", "Standardlautsprecher gewechselt.", mac)

    async def action(self, mac, action):
        if action == "default":
            await self.select_default(mac)
            return
        async with self.lock:
            if action == "pair":
                await self.bluetooth.pair(mac, self.paired)
            elif action == "connect":
                await self.bluetooth.connect(mac)
                self.manually_disconnected.discard(mac)
                self.next_retry = 0
            elif action == "disconnect":
                self.manually_disconnected.add(mac)
                await self.bluetooth.disconnect(mac)
            elif action == "trust":
                await self.bluetooth.trust(mac, True)
            elif action == "untrust":
                await self.bluetooth.trust(mac, False)
            elif action == "test":
                await self.audio.test(mac)
            elif action in {"remove", "unpair"}:
                await self.bluetooth.remove(mac)
                self.repo.remove(mac)
                self.manually_disconnected.discard(mac)
            else:
                raise PlayerError("Unbekannte Geräteaktion", "invalid")
            self.record("bluetooth.action", f"Geräteaktion {action} ausgeführt.", mac)

    async def configure(self, settings):
        async with self.lock:
            await self.lyrion.stop()
            self.repo.save_settings(settings)
            self.settings = settings
            self.bluetooth.settings = self.audio.settings = self.lyrion.settings = settings
            if settings.player_mac:
                self.lyrion.player_id = settings.player_mac
            self.next_retry = 0
            self.record("settings.changed", "Einstellungen aktualisiert.")

    async def events(self):
        queue = asyncio.Queue(maxsize=2)
        self.subscribers.add(queue)
        try:
            yield self.snapshot or await self.collect()
            while True:
                yield await queue.get()
        finally:
            self.subscribers.discard(queue)
