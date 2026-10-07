from functools import lru_cache
from typing import Any, Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting the app reads, from the environment or .env. .env.example lists them all (a test checks)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8370  # local default, derived from the app's name; the container uses 8000
    log_json: bool = False  # JSON log lines (the deploy sets it)
    database_url: str = "postgresql://dottie:dottie@localhost:54845/dottie"
    database_entra_auth: bool = False  # Azure: a managed identity token instead of a password (the deploy sets it)

    # --- The engine: the dispatcher that wakes dotties and the scheduler that fires their schedules ---
    engine_enabled: bool = True  # tests turn it off and drive the dispatcher by hand
    poll_seconds: float = 0.5  # how often the dispatcher looks for pending messages and due schedules
    run_timeout_seconds: int = 900  # a dottie that is awake longer than this is put back to sleep
    max_message_depth: int = 5  # hops (dottie to dottie) a conversation may take before it must go through a human
    max_workers: int = 4  # dotties awake at the same time
    user_timezone: str = "UTC"  # what "now" means to the dotties, e.g. Europe/Brussels

    # --- The model: Azure Foundry's OpenAI v1 endpoint, or any OpenAI-compatible gateway ---
    llm_base_url: str = ""  # e.g. https://<resource>.openai.azure.com/openai/v1/ ; empty: dotties cannot think yet
    llm_api_key: SecretStr = SecretStr("")  # empty with an Azure endpoint: the managed identity is used
    llm_model: str = ""  # the deployment name; a dottie may override it
    llm_use_responses_api: bool = True

    # --- Where the agent's loop runs ---
    agent_mode: Literal["app", "sandbox"] = "app"  # app: in this process; sandbox: inside the dottie's own sandbox
    serve: Literal["all", "internal"] = "all"  # internal: only the sandbox callback API (the gateway app on Azure)
    public_url: str = ""  # how a sandbox reaches this app (agent_mode=sandbox); empty: http://localhost:<port> (docker)

    # --- The sandbox: a dottie's own computer ---
    sandbox_backend: Literal["none", "docker", "aca"] = "none"  # none: no shell, only the wiki
    sandbox_image: str = "python:3.14-slim"  # docker backend
    sandbox_docker_network: str = "host"  # docker backend: host lets a sandbox reach this app on localhost
    azure_subscription_id: str = ""  # aca backend: where the sandbox group lives
    azure_resource_group: str = ""
    sandbox_group: str = ""
    sandbox_region: str = ""
    sandbox_idle_seconds: int = 120  # keep a dottie's sandbox running this long after its last run (for follow-ups)

    @property
    def callback_url(self) -> str:
        """Where the agent in a sandbox finds this app."""
        return (self.public_url or f"http://localhost:{self.port}").rstrip("/")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @property
    def db_url(self) -> str:
        """DATABASE_URL with the psycopg 3 driver, whatever scheme it was given in (Azure hands out postgresql://)."""
        scheme, _, rest = self.database_url.partition("://")
        return f"postgresql+psycopg://{rest}" if scheme in ("postgres", "postgresql") else self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


def settings_without_env_file(**values: Any) -> Settings:
    """Settings from these values and the environment only: .env is not read (tests, tools)."""
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]  (pydantic-settings' init option)
