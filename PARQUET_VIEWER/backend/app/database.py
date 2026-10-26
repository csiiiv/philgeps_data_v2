"""Bounded DuckDB connection factory for trusted query templates.

All connections are cursors of one shared in-memory DuckDB instance. The
instance (and with it the buffer manager and Parquet metadata cache) is
created once and reused for the process lifetime; per-request work checks
out a cursor from a bounded pool. A single `memory_limit` therefore bounds
the whole service instead of multiplying per connection, and repeated
scans of the same Parquet files hit warm buffers.
"""

from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore

import duckdb

from .config import Settings


class DuckDBPool:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._slots = BoundedSemaphore(settings.duckdb.max_concurrent_queries)
        settings.cache_directory.mkdir(parents=True, exist_ok=True)
        self.temp_directory = settings.cache_directory / "duckdb_temp"
        self.temp_directory.mkdir(parents=True, exist_ok=True)
        self._instance: duckdb.DuckDBPyConnection | None = None
        self._instance_lock = threading.Lock()
        self._cursors: queue.LifoQueue = queue.LifoQueue()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect()
        connection.execute(f"SET threads = {self.settings.duckdb.threads}")
        connection.execute("SET preserve_insertion_order = false")
        memory = self.settings.duckdb.memory_limit.replace("'", "''")
        temp = self.temp_directory.as_posix().replace("'", "''")
        connection.execute(f"SET memory_limit = '{memory}'")
        connection.execute(f"SET temp_directory = '{temp}'")
        return connection

    def _instance_connection(self) -> duckdb.DuckDBPyConnection:
        """The shared instance, configured once; safe to call concurrently."""
        if self._instance is None:
            with self._instance_lock:
                if self._instance is None:
                    self._instance = self._connect()
        return self._instance

    @contextmanager
    def connection(self):
        self._slots.acquire()
        cursor = None
        try:
            try:
                cursor = self._cursors.get_nowait()
            except queue.Empty:
                cursor = self._instance_connection().cursor()
            yield cursor
            self._cursors.put(cursor)
            cursor = None
        finally:
            if cursor is not None:
                # Yield path failed: reset the cursor; drop it if unusable so
                # the next caller gets a fresh one instead of a broken cursor.
                try:
                    cursor.execute("ROLLBACK")
                    self._cursors.put(cursor)
                except duckdb.Error:
                    try:
                        cursor.close()
                    except duckdb.Error:
                        pass
            self._slots.release()

    def close(self) -> None:
        """Release the shared instance (tests build many apps per process)."""
        while True:
            try:
                self._cursors.get_nowait().close()
            except queue.Empty:
                break
            except duckdb.Error:
                pass
        if self._instance is not None:
            try:
                self._instance.close()
            except duckdb.Error:
                pass
            self._instance = None


def sql_literal_path(path: Path) -> str:
    """Quote a trusted, configuration-owned filesystem path."""
    return "'" + str(path).replace("'", "''") + "'"


def execute_bounded(
    pool: "DuckDBPool",
    sql: str,
    parameters: list,
    deadline_seconds: float,
) -> tuple[list[str], list[tuple], float]:
    """Run one query under a watchdog that interrupts DuckDB on deadline.

    Returns (column names, rows, elapsed_ms); raises QueryError on timeout or
    execution failure so callers translate codes into HTTP responses.
    """
    from .query import QUERY_ERROR_EXECUTION, QUERY_ERROR_TIMEOUT, QueryError
    from threading import Timer
    from time import perf_counter

    started = perf_counter()
    timed_out: list[str] = []
    with pool.connection() as connection:
        interrupt = getattr(connection, "interrupt", None)
        watchdog = None
        if deadline_seconds > 0 and callable(interrupt):
            watchdog = Timer(
                deadline_seconds, lambda: (timed_out.append("1"), interrupt())
            )
            watchdog.daemon = True
            watchdog.start()
        try:
            cursor = connection.execute(sql, parameters)
            names = [item[0] for item in cursor.description]
            values = cursor.fetchall()
        except Exception as error:
            if timed_out:
                raise QueryError(
                    QUERY_ERROR_TIMEOUT,
                    f"Query exceeded the {deadline_seconds:g}s deadline and was interrupted",
                ) from error
            raise QueryError(
                QUERY_ERROR_EXECUTION, f"Query execution failed: {type(error).__name__}"
            ) from error
        finally:
            if watchdog is not None:
                watchdog.cancel()
    return names, values, round((perf_counter() - started) * 1000, 1)
