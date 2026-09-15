"""Typed service settings; this is the sole environment-variable boundary."""

from typing import Annotated

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

E164 = Annotated[str, Field(pattern=r"^\+[1-9]\d{1,14}$")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    acs_endpoint: AnyHttpUrl
    acs_source_phone_number: E164
    my_mobile_number: E164
    azure_ai_endpoint: AnyHttpUrl
    acs_callback_audience: AnyHttpUrl
    entra_tenant_id: str
    entra_client_id: str
    authorized_agent_app_ids: tuple[str, ...]
    mcp_allowed_hosts: tuple[str, ...]
    locale: str = "en-US"
    voice_name: str = "en-US-AvaMultilingualNeural"
    deadline_seconds: int = Field(default=210, gt=0)
    work_cutoff_seconds: int = Field(default=205, gt=0)
    poll_interval_milliseconds: int = Field(default=500, gt=0)
    retention_hours: int = Field(default=24, gt=0)

    @field_validator("authorized_agent_app_ids", "mcp_allowed_hosts", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> tuple[str, ...] | object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.work_cutoff_seconds >= self.deadline_seconds:
            raise ValueError("work_cutoff_seconds must be less than deadline_seconds")
        if not self.authorized_agent_app_ids:
            raise ValueError("authorized_agent_app_ids must not be empty")
        if not self.mcp_allowed_hosts:
            raise ValueError("mcp_allowed_hosts must not be empty")
        return self
