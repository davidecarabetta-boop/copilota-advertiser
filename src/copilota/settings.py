"""Configurazione da variabili d'ambiente / .env. Mai loggare questi valori."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_ads_developer_token: SecretStr | None = None
    google_ads_client_id: str | None = None
    google_ads_client_secret: SecretStr | None = None
    google_ads_refresh_token: SecretStr | None = None
    google_ads_login_customer_id: str | None = None

    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    meta_access_token: SecretStr | None = None

    gcp_project_id: str | None = None
    bq_dataset: str = "copilota"

    pilot_google_customer_id: str | None = None
    pilot_meta_ad_account_id: str | None = None


def get_settings() -> Settings:
    return Settings()
