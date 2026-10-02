import asyncio
from app.errors import PlayerError


async def command(*args, timeout=10):
    try:
        process = await asyncio.create_subprocess_exec(*map(str, args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except (FileNotFoundError, OSError):
        raise PlayerError(f"Benötigtes Programm {args[0]} ist nicht verfügbar") from None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise PlayerError(f"{args[0]} konnte die Aktion nicht ausführen. Prüfen Sie den Dienst und die Geräteverbindung.")
    return stdout.decode("utf-8", "replace")
