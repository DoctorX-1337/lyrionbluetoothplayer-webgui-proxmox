import asyncio
import platform
import socket
from pathlib import Path
import psutil
from app.process import command
from app.errors import PlayerError


class SystemManager:
    async def status(self):
        virt = "unknown"
        try:
            virt = (await command("systemd-detect-virt")).strip()
        except PlayerError:
            pass
        ips = [a.address for values in psutil.net_if_addrs().values() for a in values if a.family == socket.AF_INET and not a.address.startswith("127.")]
        memory = psutil.virtual_memory()
        import time
        return {"hostname": socket.gethostname(), "ip": ips[0] if ips else "", "platform": "Proxmox LXC" if virt == "lxc" else "VM" if virt in {"kvm", "qemu"} else virt,
                "os": platform.freedesktop_os_release().get("PRETTY_NAME", platform.system()) if platform.system() == "Linux" else platform.system(),
                "cpu": psutil.cpu_percent(), "ram": memory.percent, "ram_used": memory.used, "ram_total": memory.total,
                "uptime": max(0, time.time() - psutil.boot_time())}

    async def services(self):
        results = {}
        for name, user in (("bluetooth", False), ("dbus", False), ("pipewire", True), ("pipewire-pulse", True), ("wireplumber", True)):
            args = ["systemctl"] + (["--user"] if user else []) + ["is-active", f"{name}.service"]
            try:
                results[name] = (await command(*args, timeout=4)).strip() == "active"
            except (PlayerError, TimeoutError):
                results[name] = False
        try:
            import json
            results["rfkill"] = json.loads(await command("rfkill", "--json"))
        except (PlayerError, ValueError, TimeoutError):
            results["rfkill"] = None
        return results
