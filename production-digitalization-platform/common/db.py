"""Small PostgreSQL / TimescaleDB helper with connection retry."""
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from common import config
from common.log import get_logger

log = get_logger("db")


def connect(retries: int = 60, delay: float = 2.0):
    last = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=config.DB_HOST,
                port=config.DB_PORT,
                dbname=config.DB_NAME,
                user=config.DB_USER,
                password=config.DB_PASSWORD,
            )
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as exc:
            last = exc
            log.info("Waiting for database (%s/%s): %s", attempt, retries, str(exc).strip()[:80])
            time.sleep(delay)
    raise RuntimeError(f"Database not reachable: {last}")


@contextmanager
def cursor(conn, dict_rows: bool = False):
    factory = psycopg2.extras.RealDictCursor if dict_rows else None
    cur = conn.cursor(cursor_factory=factory)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def insert_many(cur, table: str, columns: list[str], rows: list[tuple], on_conflict: str = "") -> None:
    if not rows:
        return
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s {on_conflict}"
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)


def json_param(value):
    return psycopg2.extras.Json(value)
