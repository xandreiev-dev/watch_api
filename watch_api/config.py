from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    sql_hostname: str
    sql_port: int
    sql_username: str
    sql_password: str
    sql_database: str
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_password: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            sql_hostname=_env("SQL_HOSTNAME", "localhost"),
            sql_port=int(_env("SQL_PORT", "3306")),
            sql_username=_env("SQL_USERNAME"),
            sql_password=_env("SQL_PASSWORD"),
            sql_database=_env("SQL_DATABASE"),
            ssh_host=_env("SSH_HOST"),
            ssh_port=int(_env("SSH_PORT", "22")),
            ssh_user=_env("SSH_USER"),
            ssh_password=_env("SSH_PASSWORD"),
        )


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


settings = Settings.from_env()
