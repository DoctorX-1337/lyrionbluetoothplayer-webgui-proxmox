import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from app.errors import PlayerError
from app.models import DeviceEdit, PairAnswer, Settings, Volume, mac_address


def manager_app(manager, lifecycle=True):
    from app.updates import UpdateChecker
    updates = UpdateChecker()
    @asynccontextmanager
    async def lifespan(app):
        if lifecycle:
            await manager.start()
        try:
            yield
        finally:
            if lifecycle:
                await manager.stop()

    api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @api.exception_handler(PlayerError)
    async def player_error(request, exc):
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=404 if exc.code == "not_found" else 409)

    @api.exception_handler(TimeoutError)
    async def timeout_error(request, exc):
        return JSONResponse({"detail": "Die Aktion hat zu lange gedauert. Prüfen Sie Lautsprecher und Dienste.", "code": "timeout"}, status_code=504)

    @api.get("/api/status")
    async def status():
        return manager.snapshot or await manager.collect()

    @api.get("/api/events")
    async def events():
        async def stream():
            async for snapshot in manager.events():
                yield "event: status\ndata: " + json.dumps(snapshot) + "\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    @api.get("/api/bluetooth/devices")
    async def devices():
        return (await status())["bluetooth"]["devices"]

    @api.post("/api/bluetooth/scan/{action}")
    async def scan(action: str):
        if action not in {"start", "stop"}:
            raise PlayerError("Ungültige Suchaktion", "invalid")
        await manager.bluetooth.scan(action == "start")
        return {"ok": True}

    @api.post("/api/bluetooth/power")
    async def power(volume: dict):
        if type(volume.get("powered")) is not bool:
            raise PlayerError("Adapterstatus muss wahr oder falsch sein", "invalid")
        await manager.bluetooth.powered(volume["powered"])
        return {"ok": True}

    @api.post("/api/pairing/{ident}")
    async def pairing(ident: str, answer: PairAnswer):
        manager.bluetooth.agent.answer(ident, answer.accepted, answer.value)
        return {"ok": True}

    def validate(mac):
        try:
            return mac_address(mac)
        except ValueError as exc:
            raise PlayerError(str(exc), "invalid") from None

    @api.patch("/api/bluetooth/{mac}")
    async def edit(mac: str, values: DeviceEdit):
        mac = validate(mac)
        if not manager.repo.get(mac):
            raise PlayerError("Gerät ist noch nicht gespeichert", "not_found")
        return manager.repo.remember(mac, **values.model_dump())

    @api.delete("/api/bluetooth/{mac}")
    async def remove(mac: str, confirm: bool = Query(False)):
        if not confirm:
            raise PlayerError("Bitte bestätigen Sie das Entfernen des Lautsprechers.", "confirmation_required")
        await manager.action(validate(mac), "remove")
        return {"ok": True}

    @api.post("/api/bluetooth/{mac}/{action}")
    async def device_action(mac: str, action: str, confirm: bool = Query(False)):
        if action in {"unpair", "remove"} and not confirm:
            raise PlayerError("Bitte bestätigen Sie das Entkoppeln des Lautsprechers.", "confirmation_required")
        await manager.action(validate(mac), action)
        return {"ok": True}

    @api.get("/api/audio/status")
    async def audio():
        return (await status())["audio"]

    @api.post("/api/audio/volume")
    async def volume(value: Volume):
        actual = await manager.audio.volume(value.value)
        return {"value": actual}

    @api.get("/api/lyrion/status")
    async def lyrion():
        return (await status())["lyrion"]

    @api.post("/api/lyrion/test")
    async def test_lms(settings: Settings):
        from app.lyrion import LyrionManager
        return {"ok": True, "result": await LyrionManager(settings).rpc(["version", "?"], player="")}

    @api.post("/api/lyrion/{action}")
    async def control(action: str):
        await manager.lyrion.control(action)
        return {"ok": True}

    @api.get("/api/system/status")
    async def system():
        return (await status())["system"]

    @api.get("/api/settings")
    async def settings():
        return manager.settings

    @api.put("/api/settings")
    async def save_settings(values: Settings):
        await manager.configure(values)
        return {"ok": True}

    @api.get("/api/diagnostics")
    async def diagnostics():
        return await status()

    @api.get("/api/update/status")
    async def update_status():
        return updates.status()

    @api.post("/api/update/check")
    async def update_check():
        return await updates.check()

    @api.post("/api/update/install")
    async def update_install():
        return updates.request()

    @api.post("/api/services/{service}/restart")
    async def restart(service: str):
        if service == "squeezelite":
            await manager.lyrion.restart()
        elif service == "bluetooth-manager":
            async with manager.lock:
                await manager.bluetooth.close()
                manager.bluetooth.bus = None
                manager.bluetooth.owner = None
                manager.next_retry = 0
        elif service in {"pipewire", "wireplumber", "pipewire-pulse", "web"}:
            from app.process import command
            unit = "lyrion-bt-web" if service == "web" else service
            await command("systemctl", "--user", "--no-block", "restart", unit + ".service")
        else:
            raise PlayerError("Dieser Dienst darf nicht über die Anwendung neu gestartet werden.", "invalid")
        return {"ok": True}

    return api
