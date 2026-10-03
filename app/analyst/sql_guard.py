"""
Guardrails for LLM-generated SQL.

An LLM writing SQL is untrusted input. Before anything runs we require:
  • exactly one statement, and it is a SELECT (CTEs allowed)
  • every table referenced is on the allowlist (CTE names excepted)
  • no table functions (read_parquet, read_csv, glob, ...) → no file access
  • no dangerous functions anywhere in the tree
  • a LIMIT, injected if missing, capped at MAX_ROWS
Defence in depth: the DuckDB connection itself also has external access
disabled and its configuration locked (see warehouse.py).
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

MAX_ROWS = 200
BLOCKED_FUNCS = {
    "read_parquet", "read_csv", "read_csv_auto", "read_json", "read_json_auto", "read_text",
    "read_blob", "glob", "parquet_scan", "parquet_metadata", "sniff_csv", "query_table", "query",
    "getenv", "current_setting", "pragma_database_list", "duckdb_settings",
}


class UnsafeSQL(ValueError):
    pass


def validate(sql: str, allowed_tables: set[str]) -> str:
    """Return a safe, LIMITed version of `sql` or raise UnsafeSQL."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQL(f"could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeSQL(f"only SELECT queries are allowed (got {tree.key.upper()})")

    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Pragma, exp.Copy):
        if tree.find(bad):
            raise UnsafeSQL(f"{bad.__name__.upper()} is not allowed")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables}
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func) or table.find(exp.Anonymous):
            raise UnsafeSQL("table functions are not allowed")
        name = table.name.lower()
        if table.db or table.catalog:
            raise UnsafeSQL("schema-qualified tables are not allowed")
        if name not in allowed and name not in cte_names:
            raise UnsafeSQL(f"table '{table.name}' is not in the allowlist {sorted(allowed)}")

    for fn in tree.find_all(exp.Func):
        fname = (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).lower()
        if fname in BLOCKED_FUNCS:
            raise UnsafeSQL(f"function {fname}() is not allowed")

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        try:
            n = int(limit.expression.this)
        except (AttributeError, TypeError, ValueError):
            raise UnsafeSQL("LIMIT must be a literal integer")
        if n > MAX_ROWS:
            tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="duckdb")
