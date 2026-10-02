import asyncio
import json
import socket
import uuid
import httpx
from app.errors import PlayerError


class LyrionManager:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.player_id = settings.player_mac or ":".join(f"{uuid.getnode():012x}"[i:i+2] for i in range(0, 12, 2))
        self.volume_initialized = False

    async def rpc(self, command, player=None):
        if not self.settings.lms_host:
            raise PlayerError("Tragen Sie zuerst die LMS-Serveradresse ein.", "no_lms")
        url = f"http://{self.settings.lms_host}:{self.settings.lms_port}/jsonrpc.js"
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.post(url, json={"id": 1, "method": "slim.request", "params": [self.player_id if player is None else player, command]})
                response.raise_for_status()
                body = response.json()
                if "error" in body:
                    raise PlayerError("Der Lyrion Server hat die Anfrage abgelehnt.")
                return body.get("result", {})
        except (httpx.HTTPError, ValueError):
            raise PlayerError("Lyrion Music Server ist nicht erreichbar. Prüfen Sie Adresse und Port.", "lms_offline") from None

    async def status(self):
        running = bool(self.process and self.process.returncode is None)
        base = {"connected": False, "server_reachable": False, "running": running, "server": self.settings.lms_host,
                "player_name": self.settings.player_name, "player_id": self.player_id,
                "title": "", "artist": "", "album": "", "mode": "stop", "elapsed": 0, "duration": 0, "volume": None}
        if not self.settings.lms_host:
            return base
        try:
            await self.rpc(["version", "?"], player="")
            base["server_reachable"] = True
            result = await self.rpc(["status", "-", "1", "tags:alK"])
            base["connected"] = bool(result.get("player_connected"))
            base["mode"] = result.get("mode", "stop")
            base["elapsed"] = result.get("time", 0)
            base["volume"] = result.get("mixer volume")
            tracks = result.get("playlist_loop", [])
            if tracks:
                track = tracks[0]
                for key in ("title", "artist", "album", "duration"):
                    base[key] = track.get(key, base.get(key))
            if base["connected"] and not self.volume_initialized:
                await self.rpc(["mixer", "volume", str(min(self.settings.start_volume, self.settings.max_volume))])
                self.volume_initialized = True
        except PlayerError:
            pass
        return base

    async def control(self, action):
        commands = {"pause": ["pause", "1"], "play": ["play"], "stop": ["stop"], "next": ["playlist", "index", "+1"], "previous": ["playlist", "index", "-1"]}
        if action not in commands:
            raise PlayerError("Unbekannte Wiedergabeaktion", "invalid")
        return await self.rpc(commands[action])

    async def start(self):
        if self.process and self.process.returncode is None:
            return
        if not self.settings.auto_start or not self.settings.lms_host:
            return
        args = ["squeezelite", "-n", self.settings.player_name, "-m", self.player_id,
                "-s", f"{self.settings.lms_host}:{self.settings.slimproto_port}", "-o", "default"]
        try:
            self.process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            self.volume_initialized = False
        except OSError:
            raise PlayerError("Squeezelite konnte nicht gestartet werden. Prüfen Sie die Installation.") from None

    async def stop(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None

    async def restart(self):
        await self.stop()
        await self.start()
