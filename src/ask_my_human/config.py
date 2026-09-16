"""Typed service settings; this is the sole environment-variable boundary."""

import re
from typing import Annotated

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    acs_endpoint: AnyHttpUrl
    acs_source_phone_number: SecretStr
    my_mobile_number: SecretStr
    azure_ai_endpoint: AnyHttpUrl
    acs_callback_audience: AnyHttpUrl
    entra_tenant_id: str
    entra_client_id: str
    # NoDecode keeps comma-separated environment values out of the JSON decoder.
    authorized_agent_app_ids: Annotated[tuple[str, ...], NoDecode]
    mcp_allowed_hosts: Annotated[tuple[str, ...], NoDecode]
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

    @field_validator("acs_source_phone_number", "my_mobile_number", mode="before")
    @classmethod
    def validate_phone_number(cls, value: object) -> object:
        candidate = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(candidate, str) or E164_PATTERN.fullmatch(candidate) is None:
            raise ValueError("phone number must use E.164 format")
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
