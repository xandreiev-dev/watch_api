from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from watch_api.config import settings


class DatabaseConnectionError(RuntimeError):
    pass


@contextmanager
def get_connection() -> Iterator[pymysql.connections.Connection]:
    tunnel = None
    connection = None
    try:
        host = settings.sql_hostname
        port = settings.sql_port

        if settings.ssh_host:
            from sshtunnel import SSHTunnelForwarder

            tunnel = SSHTunnelForwarder(
                (settings.ssh_host, settings.ssh_port),
                ssh_username=settings.ssh_user,
                ssh_password=settings.ssh_password,
                remote_bind_address=(settings.sql_hostname, settings.sql_port),
            )
            tunnel.start()
            host = "127.0.0.1"
            port = tunnel.local_bind_port

        connection = pymysql.connect(
            host=host,
            port=port,
            user=settings.sql_username,
            password=settings.sql_password,
            database=settings.sql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
            read_timeout=10,
            write_timeout=10,
        )
        yield connection
    except Exception as exc:
        mode = "SSH tunnel" if settings.ssh_host else "direct MySQL"
        raise DatabaseConnectionError(
            f"Cannot connect to database using {mode}: "
            f"{settings.sql_hostname}:{settings.sql_port}, database={settings.sql_database}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
        if tunnel is not None:
            tunnel.stop()
