from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMAIL_CHECK_", env_file=".env", extra="forbid", frozen=True
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allow_non_loopback: bool = False
    checkpoint_path: Path | None = None
    checkpoint_id: str | None = Field(default=None, max_length=300)
    model_backend: Literal["laya", "test_double"] = "laya"
    cache_entries: int = Field(default=16, ge=0, le=128)
    metadata_db_path: Path = Path("data/metadata.sqlite3")
    gmail_client_file: Path | None = None
    gmail_deadline_seconds: float = Field(default=20, gt=0, le=120, allow_inf_nan=False)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_body_characters: int = Field(default=100_000, gt=0)
    max_links: int = Field(default=200, gt=0)
    scan_deadline_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    queue_size: int = Field(default=1, ge=1, le=100)
    mode: Literal["production", "development", "test"] = "production"

    @model_validator(mode="before")
    @classmethod
    def empty_checkpoint(cls, values):
        values = dict(values)
        for key in ("checkpoint_path", "checkpoint_id", "gmail_client_file"):
            if values.get(key) == "":
                values[key] = None
        return values

    @model_validator(mode="after")
    def validate_host(self):
        if self.model_backend == "test_double" and self.mode == "production":
            raise ValueError("Test double requires explicit development or test mode")
        if self.host == "localhost":
            return self
        try:
            address = ip_address(self.host)
        except ValueError as error:
            raise ValueError("Host must be localhost or an IP address") from error
        if not address.is_loopback and not self.allow_non_loopback:
            raise ValueError("Non-loopback binding requires explicit opt-in")
        return self

    @property
    def authorities(self) -> set[str]:
        hosts = {"localhost", "127.0.0.1", "[::1]", self.host}
        if ":" in self.host:
            hosts.discard(self.host)
            hosts.add(f"[{self.host}]")
        return {f"{host}:{self.port}" for host in hosts} | (hosts if self.port == 80 else set())

    @property
    def origins(self) -> set[str]:
        return {f"http://{authority}" for authority in self.authorities}
