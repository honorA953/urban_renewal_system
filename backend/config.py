from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DB_HOST: str = "mariadb"
    DB_PORT: int = 3306
    DB_NAME: str = "urban_renewal_db"
    DB_USER: str = "urban_renewal_app"
    DB_PASSWORD: str = ""
    # If set, connects via this Unix socket instead of DB_HOST/DB_PORT (TCP). Used on
    # the NAS where the target MariaDB's TCP port is occupied by an unrelated container,
    # so the app talks to the native MariaDB package directly through its socket file.
    DB_SOCKET: str = ""

    JWT_SECRET: str = "dev-only-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    UPLOAD_DIR: str = "/app/uploads"
    CORS_ORIGINS: str = "http://localhost:8080"
    ALERT_UNCONTACTED_DAYS: int = 14

    ADMIN_INITIAL_PASSWORD: str = "Admin@2026"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    @property
    def database_url(self) -> str:
        # DB_USER/DB_PASSWORD must be percent-encoded before going into the connection
        # URL - otherwise special characters (e.g. a literal "@" in the password) get
        # misinterpreted as URL syntax (like the user:pass/host separator) and silently
        # corrupt the parsed host/credentials instead of raising a clear error.
        user = quote_plus(self.DB_USER)
        password = quote_plus(self.DB_PASSWORD)
        if self.DB_SOCKET:
            return f"mysql+pymysql://{user}:{password}@/{self.DB_NAME}?unix_socket={self.DB_SOCKET}&charset=utf8mb4"
        return f"mysql+pymysql://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
