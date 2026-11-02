from psycopg_pool import ConnectionPool
from app.config import DATABASE_URL_ENV, DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

if DATABASE_URL_ENV:
    DATABASE_URL = DATABASE_URL_ENV
else:
    DATABASE_URL = (
        f"host={DB_HOST} "
        f"port={DB_PORT} "
        f"dbname={DB_NAME} "
        f"user={DB_USER} "
        f"password={DB_PASSWORD}"
    )

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=5,
    open=False,
)


def open_pool():
    if pool.closed:
        pool.open()
