"""Optional PostgreSQL persistence for the canonical SI session owner.

No SI decisions live here. JSON state and revision checks remain in lane_session.
Use a direct connection: session advisory locks cannot use transaction pooling.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
import re
import threading
from typing import Any


class SessionStorageError(RuntimeError):
    """A configured store is unavailable; never silently switch persistence."""


_HELD = threading.local()
_TABLE = "public.si_runtime_sessions"


class PostgresSessionStore:
    def __init__(self, database_url: str, namespace: str):
        if not database_url:
            raise SessionStorageError("SI_SESSION_DATABASE_URL is required for postgres sessions")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", namespace):
            raise SessionStorageError("SI_SESSION_NAMESPACE must be an explicit 1-100 character project identifier")
        try:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
        except ImportError:
            raise SessionStorageError("Postgres sessions require the optional psycopg[binary] dependency") from None
        try:
            options = conninfo_to_dict(database_url)
        except psycopg.Error:
            raise SessionStorageError("Invalid SI_SESSION_DATABASE_URL") from None
        host = options.get("host", "").lower()
        if not host or "," in host or "-pooler." in host:
            raise SessionStorageError("Postgres sessions require one explicit direct database host, without transaction pooling")
        local = host in {"localhost", "127.0.0.1", "::1"} or host.startswith("/")
        if not local:
            if options.get("sslmode", "verify-full") != "verify-full":
                raise SessionStorageError("Remote session databases require sslmode=verify-full")
            options["sslmode"] = "verify-full"
            options.setdefault("sslrootcert", "system")
        options.setdefault("connect_timeout", "10")
        options["application_name"] = "selective-intelligence-sessions"
        self._driver = psycopg
        self._options = options
        self.namespace = namespace
        self._identity = hashlib.sha256(database_url.encode()).hexdigest()

    def _key(self, session_id: str) -> tuple:
        # Forked children must never reuse an inherited connection/lock record.
        return (os.getpid(), self._identity, self.namespace, session_id)

    def _connect(self):
        connection = None
        try:
            connection = self._driver.connect(**self._options, autocommit=True)
            connection.execute("SET statement_timeout = '30s'")
            connection.execute("SET lock_timeout = '30s'")
            return connection
        except self._driver.Error:
            if connection is not None:
                connection.close()
            raise SessionStorageError("Cannot connect to the configured Postgres session store") from None

    def _execute(self, connection, statement: str, values=()):
        try:
            return connection.execute(statement, values)
        except self._driver.Error:
            raise SessionStorageError("Postgres session operation failed; no local fallback was used") from None

    @contextmanager
    def lock(self, session_id: str):
        held = getattr(_HELD, "connections", None)
        if held is None:
            held = _HELD.connections = {}
        key = self._key(session_id)
        if key in held:
            connection = held[key]
            if connection.closed or connection.broken:
                raise SessionStorageError("Postgres session lock was lost; stop and recover before retrying")
            yield connection
            return
        connection = self._connect()
        lock_id = int.from_bytes(hashlib.sha256((self.namespace + "\0" + session_id).encode()).digest()[:8], "big", signed=True)
        try:
            self._execute(connection, "SELECT pg_advisory_lock(%s::bigint)", (lock_id,))
            held[key] = connection
            try:
                yield connection
            finally:
                del held[key]
        finally:
            # Closing releases the session lock even after an error. No reconnect
            # here: a replacement connection would no longer hold this lock.
            connection.close()

    def initialize(self) -> None:
        """Explicit schema setup, never an implicit side effect of a read."""
        connection = self._connect()
        try:
            self._execute(connection, f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    namespace text NOT NULL,
                    session_id text NOT NULL,
                    revision bigint NOT NULL CHECK (revision > 0),
                    payload jsonb NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (namespace, session_id),
                    CHECK (jsonb_typeof(payload) = 'object'),
                    CHECK (payload->>'sessionId' = session_id),
                    CHECK ((payload->>'persistenceRevision')::bigint = revision)
                )
            """)
        finally:
            connection.close()

    def load(self, session_id: str) -> dict[str, Any] | None:
        with self.lock(session_id) as connection:
            row = self._execute(connection,
                f"SELECT revision, payload FROM {_TABLE} WHERE namespace = %s AND session_id = %s",
                (self.namespace, session_id)).fetchone()
            if row is None:
                return None
            revision, payload = row
            if not isinstance(payload, dict) or payload.get("persistenceRevision") != revision:
                raise SessionStorageError("Postgres session payload and stored revision disagree")
            return payload

    def save(self, session_id: str, expected: int, staged: dict[str, Any]) -> bool:
        encoded = json.dumps(staged, sort_keys=True, allow_nan=False)
        with self.lock(session_id) as connection:
            if expected == 0:
                cursor = self._execute(connection, f"""
                    INSERT INTO {_TABLE} (namespace, session_id, revision, payload)
                    VALUES (%s, %s, 1, %s::jsonb)
                    ON CONFLICT (namespace, session_id) DO NOTHING
                    RETURNING revision
                """, (self.namespace, session_id, encoded))
            else:
                cursor = self._execute(connection, f"""
                    UPDATE {_TABLE} SET revision = %s, payload = %s::jsonb, updated_at = now()
                    WHERE namespace = %s AND session_id = %s AND revision = %s
                    RETURNING revision
                """, (expected + 1, encoded, self.namespace, session_id, expected))
            return cursor.fetchone() is not None


@lru_cache(maxsize=8)
def _store(database_url: str, namespace: str) -> PostgresSessionStore:
    return PostgresSessionStore(database_url, namespace)


def configured_store() -> PostgresSessionStore | None:
    backend = os.environ.get("SI_SESSION_BACKEND", "file").strip().lower()
    if backend == "file":
        return None
    if backend != "postgres":
        raise SessionStorageError("SI_SESSION_BACKEND must be file or postgres")
    if os.environ.get("SI_SESSION_EXECUTION_MODE") != "single-active":
        raise SessionStorageError(
            "Postgres checkpoint storage requires SI_SESSION_EXECUTION_MODE=single-active; "
            "confirm the prior executor has stopped before recovery. Automatic takeover is unsupported"
        )
    return _store(os.environ.get("SI_SESSION_DATABASE_URL", ""), os.environ.get("SI_SESSION_NAMESPACE", ""))
