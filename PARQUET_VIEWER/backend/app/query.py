"""Allowlisted, parameterized row queries over registered Parquet datasets.

Includes typed filter validation, signed keyset cursors bound to the query
shape and dataset fingerprint, and bounded export with CSV formula protection.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Timer
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from .catalog import Catalog
from .config import Settings
from .database import DuckDBPool, sql_literal_path

# Stable, machine-readable error codes returned alongside HTTP errors.
QUERY_ERROR_UNKNOWN_DATASET = "unknown_dataset"
QUERY_ERROR_DATASET_NOT_QUERYABLE = "dataset_not_queryable"
QUERY_ERROR_UNKNOWN_COLUMN = "unknown_column"
QUERY_ERROR_EMPTY_PROJECTION = "empty_projection"
QUERY_ERROR_INVALID_PAGE = "invalid_page"
QUERY_ERROR_INVALID_FILTER = "invalid_filter"
QUERY_ERROR_TYPE_MISMATCH = "invalid_filter_type"
QUERY_ERROR_INVALID_CURSOR = "invalid_cursor"
QUERY_ERROR_TIMEOUT = "query_timeout"
QUERY_ERROR_EXECUTION = "query_execution"
QUERY_ERROR_INVALID_EXPORT = "invalid_export"

CURSOR_VERSION = 1


class QueryError(ValueError):
    """A client-fixable query problem with a stable error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class FilterSpec(BaseModel):
    column: str
    operator: Literal[
        "eq", "neq", "lt", "lte", "gt", "gte", "contains", "starts_with",
        "is_null", "not_null",
    ] = "eq"
    value: Any = None


class SortSpec(BaseModel):
    column: str
    direction: Literal["asc", "desc"] = "asc"


class TableQuery(BaseModel):
    columns: list[str] | None = None
    filters: list[FilterSpec] = Field(default_factory=list, max_length=20)
    filter_logic: Literal["and", "or"] = "and"
    sort: list[SortSpec] = Field(default_factory=list, max_length=5)
    page_size: int | None = None
    offset: int = Field(default=0, ge=0)
    cursor: str | None = None


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


NUMERIC_TOKENS = ("DECIMAL", "INT", "DOUBLE", "FLOAT", "REAL", "NUMERIC", "HUGEINT")


def _column_kind(type_str: str) -> str:
    t = type_str.upper()
    # Container/complex types support only null tests.
    if (
        "[" in t
        or "]" in t
        or t.startswith("STRUCT")
        or t.startswith("MAP")
        or t.startswith("UNION")
        or t.startswith("JSON")
    ):
        return "other"
    if "VARCHAR" in t or "STRING" in t or t.startswith("CHAR") or t.startswith("BPCHAR"):
        return "text"
    if any(token in t for token in NUMERIC_TOKENS):
        return "number"
    if t.startswith("DATE"):
        return "date"
    if "TIMESTAMP" in t or "DATETIME" in t:
        return "timestamp"
    if t.startswith("TIME"):
        return "time"
    if "BOOL" in t:
        return "boolean"
    return "other"


_COMPARISON_KINDS = {"text", "number", "date", "timestamp", "time", "boolean"}


def _typed_filter_value(kind: str, value: Any, column: str) -> Any:
    """Coerce/validate a filter value against the column's logical kind."""
    if kind == "text":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        raise QueryError(
            QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects a text value"
        )
    if kind == "number":
        if isinstance(value, bool):
            raise QueryError(
                QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects a number"
            )
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                Decimal(value)
            except InvalidOperation as error:
                raise QueryError(
                    QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects a number"
                ) from error
            return value  # bind as string; DuckDB casts with full precision
        raise QueryError(QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects a number")
    if kind == "date":
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise QueryError(
                QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects an ISO date (YYYY-MM-DD)"
            ) from error
    if kind == "timestamp":
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise QueryError(
                QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects an ISO timestamp"
            ) from error
    if kind == "time":
        try:
            return time.fromisoformat(str(value))
        except (TypeError, ValueError) as error:
            raise QueryError(
                QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects an ISO time"
            ) from error
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        raise QueryError(QUERY_ERROR_TYPE_MISMATCH, f"Column '{column}' expects a boolean")
    raise QueryError(
        QUERY_ERROR_TYPE_MISMATCH,
        f"Column '{column}' has type {kind} and supports only null tests",
    )


def _scalar_filter_value(value: Any) -> Any:
    """Reject objects/arrays outright (before kind-specific validation)."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise QueryError(
        QUERY_ERROR_INVALID_FILTER,
        f"Filter value must be a scalar (string, number, boolean, or null); got {type(value).__name__}",
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


# Response-size safeguards (TODO: wide-row and large-text limits).
# Very long text cells are truncated in query/export responses so one huge
# description cannot blow up a page of rows; the full value stays available
# in the underlying Parquet and via the row inspector's targeted lookups.
MAX_CELL_CHARS = 20_000
# A single row heavier than this (approx chars) is dropped entirely and
# reported; 100 such rows would otherwise dominate a 1_000-row page budget.
MAX_ROW_WEIGHT_CHARS = 400_000


def _cell_text(text: str) -> str:
    if len(text) > MAX_CELL_CHARS:
        return text[:MAX_CELL_CHARS] + f"… [+{len(text) - MAX_CELL_CHARS} chars]"
    return text


def _trunc_value(value: Any) -> Any:
    if isinstance(value, str):
        return _cell_text(value)
    if isinstance(value, list):
        return [_trunc_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _trunc_value(item) for key, item in value.items()}
    return value


def _row_payload_weight(row: dict[str, Any]) -> int:
    """Approximate serialized size of a rendered row (chars ≈ bytes for JSON)."""
    try:
        return len(json.dumps(row, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return MAX_ROW_WEIGHT_CHARS


def _trunc_value_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _trunc_value(value) for key, value in row.items()}


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


class CursorCodec:
    """Signs and verifies opaque keyset cursors with HMAC-SHA256."""

    def __init__(self, secret: str):
        self._secret = secret.encode("utf-8")

    def sign(self, payload: dict[str, Any]) -> str:
        body = _b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{body}.{signature}"

    def verify(self, token: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".", 1)
        except ValueError as error:
            raise QueryError(QUERY_ERROR_INVALID_CURSOR, "Malformed cursor") from error
        expected = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise QueryError(QUERY_ERROR_INVALID_CURSOR, "Cursor signature mismatch")
        try:
            payload = json.loads(_b64decode(body))
        except (ValueError, UnicodeDecodeError) as error:
            raise QueryError(QUERY_ERROR_INVALID_CURSOR, "Cursor payload is not valid JSON") from error
        if payload.get("v") != CURSOR_VERSION:
            raise QueryError(QUERY_ERROR_INVALID_CURSOR, "Cursor version mismatch")
        return payload


class TableQueryService:
    def __init__(self, settings: Settings, pool: DuckDBPool, catalog: Catalog):
        self.settings = settings
        self.pool = pool
        self.catalog = catalog
        self.cursors = CursorCodec(settings.api.cursor_secret or "insecure-default")

    # ------------------------------------------------------------------ plan

    def _plan(self, table_name: str, request: TableQuery) -> dict[str, Any]:
        """Validate everything and compile SQL + parameters. Returns the plan."""
        snapshot = self.catalog.snapshot()
        dataset = next(
            (item for item in snapshot["datasets"] if item["name"] == table_name), None
        )
        if dataset is None:
            raise QueryError(QUERY_ERROR_UNKNOWN_DATASET, f"Unknown dataset: {table_name}")
        if dataset["status"] != "healthy":
            raise QueryError(
                QUERY_ERROR_DATASET_NOT_QUERYABLE,
                f"Dataset is not queryable (status: {dataset['status']})",
            )

        available = {column["name"]: column for column in dataset["columns"]}
        selected = request.columns or list(available)
        unknown = [column for column in selected if column not in available]
        unknown += [item.column for item in request.filters if item.column not in available]
        unknown += [item.column for item in request.sort if item.column not in available]
        if unknown:
            raise QueryError(
                QUERY_ERROR_UNKNOWN_COLUMN,
                f"Unknown column(s): {', '.join(sorted(set(unknown)))}",
            )
        if not selected:
            raise QueryError(QUERY_ERROR_EMPTY_PROJECTION, "At least one column must be selected")

        if request.page_size is None:
            page_size = self.settings.api.default_page_size
        else:
            page_size = request.page_size
            if page_size < 1 or page_size > self.settings.api.maximum_page_size:
                raise QueryError(
                    QUERY_ERROR_INVALID_PAGE,
                    f"page_size must be between 1 and {self.settings.api.maximum_page_size}",
                )

        kinds = {name: _column_kind(column["type"]) for name, column in available.items()}
        predicates: list[str] = []
        parameters: list[Any] = []
        comparisons = {"eq": "=", "neq": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        for item in request.filters:
            column = _identifier(item.column)
            kind = kinds[item.column]
            if item.operator in comparisons:
                if kind not in _COMPARISON_KINDS:
                    raise QueryError(
                        QUERY_ERROR_TYPE_MISMATCH,
                        f"Operator '{item.operator}' is not valid for column '{item.column}' ({kind})",
                    )
                value = _scalar_filter_value(item.value)
                if value is not None:
                    value = _typed_filter_value(kind, value, item.column)
                predicates.append(f"{column} {comparisons[item.operator]} ?")
                parameters.append(value)
            elif item.operator == "is_null":
                predicates.append(f"{column} IS NULL")
            elif item.operator == "not_null":
                predicates.append(f"{column} IS NOT NULL")
            elif item.operator in {"contains", "starts_with"}:
                if kind != "text":
                    raise QueryError(
                        QUERY_ERROR_TYPE_MISMATCH,
                        f"'{item.operator}' requires a text column",
                    )
                raw = _scalar_filter_value(item.value)
                escaped = str(raw or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                parameters.append(f"%{escaped}%" if item.operator == "contains" else f"{escaped}%")
                predicates.append(f"{column} ILIKE ? ESCAPE '\\'")
            else:
                raise QueryError(
                    QUERY_ERROR_INVALID_FILTER, f"Unsupported filter operator: {item.operator}"
                )

        order = [item.model_dump() for item in request.sort]
        ordered_names = {item["column"] for item in order}
        for key in dataset["primary_key"]:
            if key not in ordered_names:
                order.append({"column": key, "direction": "asc"})

        select_sql = ", ".join(_identifier(column) for column in selected)
        relation = f"read_parquet({sql_literal_path(Path(dataset['path']))})"
        sql = f"SELECT {select_sql} FROM {relation}"
        count_sql = f"SELECT count(*) FROM {relation}"
        if predicates:
            joiner = " AND " if request.filter_logic == "and" else " OR "
            where_sql = " WHERE " + joiner.join(f"({predicate})" for predicate in predicates)
            sql += where_sql
            count_sql += where_sql
        order_columns = [item["column"] for item in order]
        order_available = all(name in available for name in order_columns)

        cursor_payload = None
        if request.cursor is not None:
            if not order_available:
                raise QueryError(QUERY_ERROR_INVALID_CURSOR, "Cursor requires sortable columns")
            cursor_payload = self.cursors.verify(request.cursor)
            expected_binding = {
                "v": CURSOR_VERSION,
                "table": table_name,
                "registry_version": snapshot["registry_version"],
                "dataset_fingerprint": snapshot["dataset_fingerprint"],
                "columns": selected,
                "sort": order,
                "filters": [item.model_dump() for item in request.filters],
                "filter_logic": request.filter_logic,
            }
            for field, expected in expected_binding.items():
                if cursor_payload.get(field) != expected:
                    raise QueryError(
                        QUERY_ERROR_INVALID_CURSOR,
                        f"Cursor does not match the current {field} / dataset state",
                    )
            keys = cursor_payload.get("keys") or []
            if len(keys) != len(order) or any(key is None for key in keys):
                raise QueryError(
                    QUERY_ERROR_INVALID_CURSOR, "Cursor key values are incomplete or null"
                )
            cursor_predicates: list[str] = []
            cursor_params: list[Any] = []
            for index, spec in enumerate(order):
                equalities = [
                    f"{_identifier(col)} = ?" for col in order_columns[:index]
                ]
                cursor_params.extend(
                    _typed_filter_value(kinds[col], keys[i], col) for i, col in enumerate(order_columns[:index])
                )
                operator = ">" if spec["direction"] == "asc" else "<"
                cursor_predicates.append(
                    "(" + " AND ".join(equalities + [f"{_identifier(spec['column'])} {operator} ?"]) + ")"
                )
                cursor_params.append(_typed_filter_value(kinds[spec["column"]], keys[index], spec["column"]))
            keyset_sql = " OR ".join(cursor_predicates)
            sql += (" WHERE " if " WHERE " not in sql else " AND ") + f"({keyset_sql})"
            parameters.extend(cursor_params)
            offset = 0
        else:
            offset = request.offset

        if order and order_available:
            sql += " ORDER BY " + ", ".join(
                f"{_identifier(item['column'])} {item['direction'].upper()} NULLS LAST" for item in order
            )

        return {
            "snapshot": snapshot,
            "dataset": dataset,
            "available": available,
            "kinds": kinds,
            "selected": selected,
            "order": order,
            "page_size": page_size,
            "offset": offset,
            "sql": sql,
            "count_sql": count_sql,
            "parameters": parameters,
        }

    # --------------------------------------------------------------- execute

    def count(self, table_name: str, request: TableQuery) -> int:
        """Count rows matching the request's filters (no projection/sort)."""
        plan = self._plan(table_name, request)
        names, rows = self._run(plan["count_sql"], plan["parameters"])
        return int(rows[0][0])

    def _run(self, sql: str, parameters: list[Any]) -> tuple[list[str], list[tuple]]:
        started = perf_counter()
        deadline = self.settings.api.query_timeout_seconds
        timed_out: list[str] = []
        with self.pool.connection() as connection:
            interrupt = getattr(connection, "interrupt", None)
            watchdog = None
            if deadline > 0 and callable(interrupt):
                watchdog = Timer(
                    deadline, lambda: (timed_out.append("1"), interrupt())
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
                        f"Query exceeded the {deadline:g}s deadline and was interrupted",
                    ) from error
                raise QueryError(
                    QUERY_ERROR_EXECUTION, f"Query execution failed: {type(error).__name__}"
                ) from error
            finally:
                if watchdog is not None:
                    watchdog.cancel()
        self.last_elapsed_ms = round((perf_counter() - started) * 1000, 1)
        return names, values

    def execute(self, table_name: str, request: TableQuery) -> dict[str, Any]:
        plan = self._plan(table_name, request)
        page_size = plan["page_size"]
        if plan["offset"] > 0:
            names, values = self._run(
                plan["sql"] + " LIMIT ? OFFSET ?",
                plan["parameters"] + [page_size + 1, plan["offset"]],
            )
        else:
            names, values = self._run(
                plan["sql"] + " LIMIT ?", plan["parameters"] + [page_size + 1]
            )
        has_more = len(values) > page_size
        values = values[:page_size]
        rows: list[dict[str, Any]] = []
        dropped_rows = 0
        for row in values:
            rendered = _trunc_value_row(dict(zip(names, (_json_value(v) for v in row))))
            if _row_payload_weight(rendered) > MAX_ROW_WEIGHT_CHARS:
                dropped_rows += 1
                continue
            rows.append(rendered)

        next_cursor = None
        if has_more and values and plan["order"]:
            last = rows[-1]
            keys = [_json_value(last.get(item["column"])) for item in plan["order"]]
            if all(key is not None for key in keys):
                next_cursor = self.cursors.sign({
                    "v": CURSOR_VERSION,
                    "table": table_name,
                    "registry_version": plan["snapshot"]["registry_version"],
                    "dataset_fingerprint": plan["snapshot"]["dataset_fingerprint"],
                    "columns": plan["selected"],
                    "sort": plan["order"],
                    "filters": [item.model_dump() for item in request.filters],
                    "filter_logic": request.filter_logic,
                    "keys": keys,
                })

        return {
            "table": table_name,
            "columns": [
                {"name": name, "type": plan["available"][name]["type"]} for name in names
            ],
            "rows": rows,
            "page": {
                "offset": plan["offset"],
                "page_size": page_size,
                "returned": len(rows),
                "has_more": has_more,
                "dropped_oversized_rows": dropped_rows,
                "next_offset": None if request.cursor else (
                    plan["offset"] + len(rows) if has_more else None
                ),
                "next_cursor": next_cursor,
                "pagination": "keyset" if request.cursor else "offset",
            },
            "elapsed_ms": self.last_elapsed_ms,
            "dataset_fingerprint": plan["snapshot"]["dataset_fingerprint"],
        }

    # ---------------------------------------------------------------- export

    def export(self, table_name: str, request: TableQuery, row_limit: int) -> dict[str, Any]:
        plan = self._plan(table_name, request)
        names, values = self._run(plan["sql"] + " LIMIT ?", plan["parameters"] + [row_limit + 1])
        truncated = len(values) > row_limit
        values = values[:row_limit]
        rows = [
            _trunc_value_row(dict(zip(names, (_json_value(v) for v in row))))
            for row in values
        ]
        return {
            "table": table_name,
            "columns": [
                {"name": name, "type": plan["available"][name]["type"]} for name in names
            ],
            "rows": rows,
            "truncated": truncated,
            "row_limit": row_limit,
            "dataset_fingerprint": plan["snapshot"]["dataset_fingerprint"],
        }


CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:
    text = "" if value is None else (value if isinstance(value, str) else json.dumps(value))
    if text[:1] in CSV_FORMULA_PREFIXES:
        text = "'" + text
    if any(ch in text for ch in (',', '"', '\n', '\r')):
        text = '"' + text.replace('"', '""') + '"'
    return text


def to_csv(payload: dict[str, Any]) -> str:
    """Render an export payload as CSV with spreadsheet-formula protection."""
    columns = [column["name"] for column in payload["columns"]]
    lines = [",".join(csv_cell(name) for name in columns)]
    for row in payload["rows"]:
        lines.append(",".join(csv_cell(row.get(name)) for name in columns))
    return "\r\n".join(lines) + "\r\n"
