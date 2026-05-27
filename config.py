from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "local-code-graph"
    debug: bool = False

    REPO_NAME: str
    TARGET_REPO_PATH: str
    LOCAL_ENDPOINT: str
    OPENAI_API_KEY: str  # Since we are using openai module, we need a dummy key here
    AI_MODEL_ID: str
    APP_NAME: str
    BACKEND_ENDPOINT: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()