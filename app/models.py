import ipaddress
import re
from pydantic import BaseModel, Field, field_validator


def mac_address(value: str) -> str:
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value):
        raise ValueError("Ungültige Bluetooth-MAC-Adresse")
    return value.upper()


class Settings(BaseModel):
    lms_host: str = ""
    lms_port: int = Field(9000, ge=1, le=65535)
    lms_cli_port: int = Field(9090, ge=1, le=65535)
    slimproto_port: int = Field(3483, ge=1, le=65535)
    player_name: str = Field("Lyrion Bluetooth", min_length=1, max_length=64)
    player_mac: str = ""
    adapter: str = "auto"
    auto_reconnect: bool = True
    auto_start: bool = True
    scan_duration: int = Field(30, ge=5, le=120)
    connect_timeout: int = Field(25, ge=5, le=90)
    start_volume: int = Field(35, ge=0, le=100)
    max_volume: int = Field(85, ge=1, le=100)
    codec_preference: str = "auto"

    @field_validator("lms_host")
    @classmethod
    def host(cls, value):
        if not value:
            return value
        try:
            address = ipaddress.ip_address(value)
            if address.version != 4:
                raise ValueError("Bitte eine IPv4-Adresse verwenden")
            return value
        except ValueError:
            if len(value) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in value.rstrip(".").split(".")):
                raise ValueError("Ungültiger Hostname oder IPv4-Adresse")
            if re.fullmatch(r"[\d.]+", value):
                raise ValueError("Ungültige IPv4-Adresse")
            return value

    @field_validator("player_mac")
    @classmethod
    def player_address(cls, value):
        return mac_address(value) if value else value

    @field_validator("adapter")
    @classmethod
    def adapter_id(cls, value):
        if value != "auto" and not re.fullmatch(r"hci\d+|(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value):
            raise ValueError("Ungültiger Adapter")
        return value

    @field_validator("player_name")
    @classmethod
    def safe_name(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Steuerzeichen sind nicht erlaubt")
        return value

    @field_validator("codec_preference")
    @classmethod
    def codec(cls, value):
        if value not in {"auto", "sbc", "sbc_xq", "aac", "aptx", "aptx_hd", "ldac"}:
            raise ValueError("Unbekannter Codec")
        return value


class DeviceEdit(BaseModel):
    friendly_name: str = Field("", max_length=64)
    auto_connect: bool = True
    preferred_volume: int = Field(35, ge=0, le=100)
    preferred_profile: str = Field("a2dp", pattern=r"^a2dp$")
    preferred_codec: str = Field("auto", pattern=r"^(auto|sbc|sbc_xq|aac|aptx|aptx_hd|ldac)$")


class Volume(BaseModel):
    value: int = Field(ge=0, le=100)


class PairAnswer(BaseModel):
    accepted: bool = True
    value: str = Field("", max_length=16)
