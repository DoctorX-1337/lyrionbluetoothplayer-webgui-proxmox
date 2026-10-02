import hashlib
import hmac
import secrets
import time
from app.errors import PlayerError


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, encoded):
    if not isinstance(encoded, str):
        return False
    try:
        _, salt, _ = encoded.split("$")
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


class Auth:
    def __init__(self, repo, config):
        self.repo, self.config = repo, config
        self.failures = {}

    def value(self, key):
        row = self.repo.db.execute("SELECT value FROM auth WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def initialize(self, password=None):
        if self.value("password"):
            return None
        password = password or secrets.token_urlsafe(18)
        with self.repo.db:
            self.repo.db.execute("INSERT INTO auth VALUES ('password',?)", (hash_password(password),))
            self.repo.db.execute("INSERT INTO auth VALUES ('must_change','1')")
        return password

    def session(self, token):
        if not token:
            return None
        row = self.repo.db.execute("SELECT csrf,expires FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row["expires"] < time.time():
            return None
        return {"csrf": row["csrf"], "must_change": self.value("must_change") == "1"}

    def login(self, username, password, ip):
        now = time.time()
        # Bounded state prevents a LAN client from growing an unbounded dictionary.
        self.failures = {k: v for k, v in self.failures.items() if v[1] > now}
        count, expires = self.failures.get(ip, (0, now + 60))
        if count >= 5:
            raise PlayerError("Zu viele Anmeldeversuche. Bitte eine Minute warten.", "rate_limit")
        if username != "admin" or not verify_password(password, self.value("password")):
            if len(self.failures) < 2048 or ip in self.failures:
                self.failures[ip] = (count + 1, expires)
            raise PlayerError("Benutzername oder Passwort ist falsch.", "login_failed")
        self.failures.pop(ip, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.repo.db:
            self.repo.db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
            self.repo.db.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, now + self.config.session_hours * 3600))
        return token, {"csrf": csrf, "must_change": self.value("must_change") == "1"}

    def logout(self, token):
        with self.repo.db:
            self.repo.db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def change_password(self, old, new, token):
        if not verify_password(old, self.value("password")):
            raise PlayerError("Das bisherige Passwort ist falsch.", "invalid")
        if len(new) < 12 or len(new) > 256:
            raise PlayerError("Das neue Passwort muss 12–256 Zeichen enthalten.", "invalid")
        if hmac.compare_digest(old, new):
            raise PlayerError("Wählen Sie ein neues Passwort.", "invalid")
        with self.repo.db:
            self.repo.db.execute("UPDATE auth SET value=? WHERE key='password'", (hash_password(new),))
            self.repo.db.execute("UPDATE auth SET value='0' WHERE key='must_change'")
            self.repo.db.execute("DELETE FROM sessions WHERE token_hash != ?", (hashlib.sha256(token.encode()).hexdigest(),))
