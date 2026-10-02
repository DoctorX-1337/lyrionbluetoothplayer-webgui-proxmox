import asyncio
import time
import uuid
from dbus_next import BusType, Message, MessageType, Variant, DBusError
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method
from app.errors import PlayerError
from app.models import mac_address

AGENT_PATH = "/org/lyrionbt/agent"


class PairingAgent(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.Agent1")
        self.requests = {}
        self.allowed = set()

    async def prompt(self, device, kind, code=""):
        if device not in self.allowed:
            raise DBusError("org.bluez.Error.Rejected", "Kein Pairing angefordert")
        ident = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.requests[ident] = {"id": ident, "device": device.rsplit("/", 1)[-1].removeprefix("dev_").replace("_", ":"),
                                "kind": kind, "code": code, "created_at": time.time(), "future": future}
        try:
            return await asyncio.wait_for(future, 90)
        except TimeoutError:
            raise DBusError("org.bluez.Error.Canceled", "Pairing-Zeit abgelaufen") from None
        finally:
            self.requests.pop(ident, None)

    def pending(self):
        return [{k: v for k, v in req.items() if k != "future"} for req in self.requests.values()]

    def answer(self, ident, accepted, value):
        req = self.requests.get(ident)
        if not req or req["future"].done():
            raise PlayerError("Pairing-Anfrage ist abgelaufen", "not_found")
        if accepted:
            if req["kind"] == "pin" and not (1 <= len(value) <= 16 and value.isascii() and value.isalnum()):
                raise PlayerError("PIN muss 1–16 Buchstaben oder Ziffern enthalten", "invalid")
            if req["kind"] == "passkey" and not (value.isdigit() and len(value) <= 6):
                raise PlayerError("Passkey muss 1–6 Ziffern enthalten", "invalid")
            req["future"].set_result(value)
        else:
            req["future"].set_exception(DBusError("org.bluez.Error.Rejected", "Abgelehnt"))

    @method()
    def Release(self):
        self.Cancel()

    @method()
    async def RequestPinCode(self, device: 'o') -> 's':
        return await self.prompt(device, "pin")

    @method()
    def DisplayPinCode(self, device: 'o', pincode: 's'):
        self.display(device, pincode)

    @method()
    async def RequestPasskey(self, device: 'o') -> 'u':
        return int(await self.prompt(device, "passkey"))

    @method()
    def DisplayPasskey(self, device: 'o', passkey: 'u', entered: 'q'):
        self.display(device, f"{passkey:06d}", entered)

    @method()
    async def RequestConfirmation(self, device: 'o', passkey: 'u'):
        await self.prompt(device, "confirmation", f"{passkey:06d}")

    @method()
    async def RequestAuthorization(self, device: 'o'):
        await self.prompt(device, "authorization")

    @method()
    async def AuthorizeService(self, device: 'o', service_uuid: 's'):
        # Only A2DP/AVRCP audio services are allowed for an explicit pairing.
        allowed_services = {"0000110b-0000-1000-8000-00805f9b34fb", "0000110d-0000-1000-8000-00805f9b34fb",
                            "0000110e-0000-1000-8000-00805f9b34fb", "0000110c-0000-1000-8000-00805f9b34fb"}
        if device not in self.allowed or service_uuid.lower() not in allowed_services:
            raise DBusError("org.bluez.Error.Rejected", "Dienst nicht autorisiert")

    def display(self, device, code, entered=0):
        if device in self.allowed:
            self.requests["display"] = {"id": "display", "device": device.rsplit("/", 1)[-1].removeprefix("dev_").replace("_", ":"),
                                        "kind": "display", "code": code, "entered": entered, "created_at": time.time()}

    @method()
    def Cancel(self):
        for req in list(self.requests.values()):
            future = req.get("future")
            if future and not future.done():
                future.set_exception(DBusError("org.bluez.Error.Canceled", "Pairing abgebrochen"))
        self.requests.clear()


class BluetoothManager:
    def __init__(self, settings):
        self.settings = settings
        self.bus = None
        self.agent = PairingAgent()
        self.scan_task = None
        self.scan_adapter = None
        self.scan_lock = asyncio.Lock()
        self.pair_tasks = {}
        self.pair_results = {}
        self.owner = None

    async def call(self, path, interface, member, signature="", body=None, timeout=30, destination="org.bluez"):
        if not self.bus:
            raise PlayerError("D-Bus ist nicht erreichbar. Prüfen Sie den D-Bus-Dienst.")
        try:
            response = await asyncio.wait_for(self.bus.call(Message(destination=destination, path=path,
                interface=interface, member=member, signature=signature, body=body or [])), timeout)
        except (TimeoutError, OSError, EOFError):
            raise PlayerError("Bluetooth antwortet nicht. Prüfen Sie Adapter und Lautsprecher.") from None
        if response.message_type == MessageType.ERROR:
            code = response.error_name.rsplit(".", 1)[-1]
            texts = {"NotReady": "Bluetooth ist ausgeschaltet oder durch rfkill blockiert.",
                     "AuthenticationFailed": "Pairing fehlgeschlagen. Versetzen Sie den Lautsprecher erneut in den Kopplungsmodus.",
                     "AuthenticationRejected": "Die Kopplung wurde abgelehnt.", "AuthenticationCanceled": "Die Kopplung wurde abgebrochen.",
                     "NotAuthorized": "Keine Bluetooth-Berechtigung. Prüfen Sie D-Bus-Regeln und LXC-Rechte.",
                     "AccessDenied": "Keine D-Bus-Berechtigung für Bluetooth.",
                     "ServiceUnknown": "BlueZ ist nicht gestartet.", "NameHasNoOwner": "BlueZ ist nicht gestartet.",
                     "AlreadyExists": "Das Gerät ist bereits gekoppelt.", "DoesNotExist": "Das Bluetooth-Gerät ist nicht mehr vorhanden.",
                     "InProgress": "Für dieses Gerät läuft bereits eine Aktion."}
            raise PlayerError(texts.get(code, "Der Bluetooth-Lautsprecher ist momentan nicht erreichbar."), code)
        return response.body

    async def ensure(self):
        try:
            if not self.bus or not self.bus.connected:
                self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                self.bus.export(AGENT_PATH, self.agent)
                self.owner = None
            owner = (await self.call("/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner", "s", ["org.bluez"], destination="org.freedesktop.DBus"))[0]
            if owner != self.owner:
                self.agent.Cancel()
                await self.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os", [AGENT_PATH, "KeyboardDisplay"])
                # Explicit Pair() from our connection uses this agent; do not replace other agents globally.
                self.owner = owner
        except PlayerError:
            raise
        except (OSError, EOFError):
            self.bus = None
            raise PlayerError("D-Bus ist nicht erreichbar. Prüfen Sie den Systemdienst.") from None

    async def objects(self):
        await self.ensure()
        result = (await self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"))[0]
        return {path: {interface: {key: value.value for key, value in props.items()} for interface, props in interfaces.items()} for path, interfaces in result.items()}

    def selected_adapter(self, objects):
        adapters = [(path, interfaces["org.bluez.Adapter1"]) for path, interfaces in objects.items() if "org.bluez.Adapter1" in interfaces]
        for path, props in sorted(adapters):
            if self.settings.adapter == "auto" or self.settings.adapter in (path.rsplit("/", 1)[-1], props.get("Address")):
                return path, props
        raise PlayerError("Kein Bluetooth-Adapter verfügbar. Prüfen Sie Hardwarezuordnung, HCI und rfkill.", "no_adapter")

    async def status(self):
        objects = await self.objects()
        path, adapter = self.selected_adapter(objects)
        adapters = [{"id": p.rsplit("/", 1)[-1], **i["org.bluez.Adapter1"]} for p, i in objects.items() if "org.bluez.Adapter1" in i]
        devices = []
        for device_path, interfaces in objects.items():
            props = interfaces.get("org.bluez.Device1")
            if not props or props.get("Adapter") != path:
                continue
            devices.append({"mac_address": props["Address"], "bluetooth_name": props.get("Name", props.get("Alias", "Unbekannt")),
                "paired": props.get("Paired", False), "trusted": props.get("Trusted", False), "connected": props.get("Connected", False),
                "rssi": props.get("RSSI"), "battery": interfaces.get("org.bluez.Battery1", {}).get("Percentage"),
                "type": props.get("Icon", "audio-card"), "uuids": props.get("UUIDs", [])})
        return {"adapter": {"id": path.rsplit("/", 1)[-1], **adapter}, "adapters": adapters,
                "devices": devices, "scanning": adapter.get("Discovering", False)}

    async def device_path(self, mac):
        mac = mac_address(mac)
        objects = await self.objects()
        adapter, _ = self.selected_adapter(objects)
        for path, interfaces in objects.items():
            props = interfaces.get("org.bluez.Device1", {})
            if props.get("Address") == mac and props.get("Adapter") == adapter:
                return path
        raise PlayerError("Gerät nicht gefunden. Starten Sie eine neue Bluetooth-Suche.", "not_found")

    async def powered(self, value):
        path, _ = self.selected_adapter(await self.objects())
        await self.call(path, "org.freedesktop.DBus.Properties", "Set", "ssv", ["org.bluez.Adapter1", "Powered", Variant("b", value)])

    async def scan(self, start=True):
        async with self.scan_lock:
            if self.scan_task:
                self.scan_task.cancel()
                await asyncio.gather(self.scan_task, return_exceptions=True)
                self.scan_task = None
            previous = self.scan_adapter
            self.scan_adapter = None
            if not start:
                if previous:
                    await self.call(previous, "org.bluez.Adapter1", "StopDiscovery")
                return
            await self.powered(True)
            path, _ = self.selected_adapter(await self.objects())
            # BlueZ tracks discovery per D-Bus client. Stop our previous session,
            # including a session whose timer was cancelled during another request.
            for owned in dict.fromkeys(p for p in (previous, path) if p):
                try:
                    await self.call(owned, "org.bluez.Adapter1", "StopDiscovery")
                except PlayerError as exc:
                    if exc.code not in {"Failed", "NotReady", "DoesNotExist"}:
                        raise
            await self.call(path, "org.bluez.Adapter1", "SetDiscoveryFilter", "a{sv}", [{"Transport": Variant("s", "bredr")}])
            await self.call(path, "org.bluez.Adapter1", "StartDiscovery")
            self.scan_adapter = path

            async def finish():
                await asyncio.sleep(self.settings.scan_duration)
                async with self.scan_lock:
                    try:
                        await self.call(path, "org.bluez.Adapter1", "StopDiscovery")
                    except PlayerError:
                        pass
                    finally:
                        self.scan_adapter = None
                        self.scan_task = None
            self.scan_task = asyncio.create_task(finish())

    async def trust(self, mac, value=True):
        path = await self.device_path(mac)
        await self.call(path, "org.freedesktop.DBus.Properties", "Set", "ssv", ["org.bluez.Device1", "Trusted", Variant("b", value)])

    async def connect(self, mac):
        await self.powered(True)
        path = await self.device_path(mac)
        try:
            await self.call(path, "org.bluez.Device1", "Connect", timeout=self.settings.connect_timeout)
        except PlayerError as exc:
            if exc.code != "AlreadyConnected":
                raise

    async def disconnect(self, mac):
        await self.call(await self.device_path(mac), "org.bluez.Device1", "Disconnect")

    async def remove(self, mac):
        path = await self.device_path(mac)
        adapter, _ = self.selected_adapter(await self.objects())
        await self.call(adapter, "org.bluez.Adapter1", "RemoveDevice", "o", [path])

    async def pair(self, mac, callback):
        mac = mac_address(mac)
        if mac in self.pair_tasks and not self.pair_tasks[mac].done():
            raise PlayerError("Für dieses Gerät läuft bereits eine Kopplung.", "busy")
        path = await self.device_path(mac)
        self.agent.allowed.add(path)
        self.pair_results[mac] = {"state": "pairing", "message": "Kopplung läuft …"}

        async def worker():
            try:
                try:
                    await self.call(path, "org.bluez.Device1", "Pair", timeout=120)
                except PlayerError as exc:
                    if exc.code != "AlreadyExists":
                        raise
                await self.trust(mac)
                await callback(mac)
                self.pair_results[mac] = {"state": "paired", "message": "Lautsprecher wurde gekoppelt."}
            except PlayerError as exc:
                self.pair_results[mac] = {"state": "error", "message": str(exc)}
            finally:
                self.agent.allowed.discard(path)
                self.agent.requests.pop("display", None)
        self.pair_tasks[mac] = asyncio.create_task(worker())

    async def close(self):
        self.agent.Cancel()
        try:
            await self.scan(False)
        except PlayerError:
            pass
        for task in self.pair_tasks.values():
            task.cancel()
        if self.bus:
            self.bus.disconnect()
