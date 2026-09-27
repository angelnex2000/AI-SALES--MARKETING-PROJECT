"""The migrations are hand-maintained, so they can drift from the models.

These tests compile the whole revision chain to Postgres DDL offline (no
database needed) and diff it against `Base.metadata`. They are the safety net
for the parts Alembic's autogenerate does not handle and that were fixed by
hand:

  * `DROP TYPE` for every enum on downgrade (autogenerate emits CREATE but
    never DROP, so `downgrade` then `upgrade` fails with "type already exists")
  * FK-safe table ordering after `deal_outcomes`, `crm_activities` and `notes`
    gained references to `deals.id`
  * **enum members**, which autogenerate does not diff at all. A model enum
    that gains a value without a matching `ALTER TYPE` passes every test that
    runs on SQLite — where the column is plain VARCHAR — and then fails in
    production on the first insert with `InvalidTextRepresentation`.

Since the project's rule is incremental revisions on top of the baseline, the
DDL is *folded* rather than read from `CREATE` statements alone: columns
added by a later `ALTER TABLE` count as present, and enum values renamed or
added by a later `ALTER TYPE` count toward the final member list. Comparing
against `CREATE TABLE`/`CREATE TYPE` only would report every incremental
change as drift.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

API_ROOT = Path(__file__).resolve().parents[1]
PG_URL = "postgresql+asyncpg://user:pass@localhost:5432/parity_check"

NON_COLUMN_KEYWORDS = {"PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK"}


def _alembic_sql(*args: str) -> str:
    """Render migration DDL without touching a database (alembic offline mode)."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args, "--sql"],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "DATABASE_URL": PG_URL,
            "SECRET_KEY": "parity-check-secret-key-long-enough-32",
            "ENVIRONMENT": "development",
        },
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} failed:\n{result.stderr[-2000:]}")
    return result.stdout


@pytest.fixture(scope="module")
def upgrade_sql() -> str:
    return _alembic_sql("upgrade", "head")


@pytest.fixture(scope="module")
def downgrade_sql() -> str:
    return _alembic_sql("downgrade", "head:base")


@pytest.fixture(scope="module")
def metadata():
    from app.models.base import Base

    return Base.metadata


def _columns_after_migrations(upgrade_sql: str) -> dict[str, set[str]]:
    """Fold CREATE TABLE + later ADD/DROP COLUMN into the final column set.

    Reading `CREATE TABLE` alone would report every column an incremental
    revision adds as missing from the migration.
    """

    columns: dict[str, set[str]] = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", upgrade_sql, re.S):
        columns[name] = set(re.findall(r"^\s{4}(\w+) ", body, re.M)) - NON_COLUMN_KEYWORDS
    for table, column in re.findall(r"ALTER TABLE (\w+) ADD COLUMN (\w+) ", upgrade_sql):
        columns.setdefault(table, set()).add(column)
    for table, column in re.findall(r"ALTER TABLE (\w+) DROP COLUMN (\w+)", upgrade_sql):
        columns.get(table, set()).discard(column)
    return columns


def _enum_values_after_migrations(upgrade_sql: str) -> dict[str, list[str]]:
    """Fold CREATE TYPE + later RENAME VALUE / ADD VALUE into the final members.

    Order matters: a rename must be applied to the list as it stood when the
    rename ran, so the statements are replayed in the order they appear.
    """

    enums: dict[str, list[str]] = {}
    statement = re.compile(
        r"CREATE TYPE (?P<created>\w+) AS ENUM \((?P<values>[^)]*)\)"
        r"|ALTER TYPE (?P<renamed>\w+) RENAME VALUE '(?P<old>[^']+)' TO '(?P<new>[^']+)'"
        r"|ALTER TYPE (?P<added>\w+) ADD VALUE (?:IF NOT EXISTS )?'(?P<value>[^']+)'"
    )
    for match in statement.finditer(upgrade_sql):
        if match.group("created"):
            enums[match.group("created")] = re.findall(r"'([^']*)'", match.group("values"))
        elif match.group("renamed"):
            values = enums.get(match.group("renamed"), [])
            enums[match.group("renamed")] = [
                match.group("new") if v == match.group("old") else v for v in values
            ]
        elif match.group("added"):
            values = enums.setdefault(match.group("added"), [])
            if match.group("value") not in values:
                values.append(match.group("value"))
    return enums


def _model_enums(metadata) -> dict[str, set[str]]:
    return {
        column.type.name: set(column.type.enums)
        for table in metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.Enum) and column.type.name
    }


def test_every_model_table_is_in_the_migration(upgrade_sql, metadata):
    created = set(re.findall(r"CREATE TABLE (\w+)", upgrade_sql))
    missing = set(metadata.tables) - created
    assert not missing, f"tables in the models but not the migration: {sorted(missing)}"


def test_columns_match_model_for_model(upgrade_sql, metadata):
    in_migration = _columns_after_migrations(upgrade_sql)
    problems = []
    for table in metadata.tables.values():
        assert table.name in in_migration, f"{table.name} missing from migration"
        in_sql = in_migration[table.name]
        in_model = {c.name for c in table.columns}
        if in_model - in_sql:
            problems.append(f"{table.name}: in model, not migration -> {sorted(in_model - in_sql)}")
        if in_sql - in_model:
            problems.append(f"{table.name}: in migration, not model -> {sorted(in_sql - in_model)}")
    assert not problems, "\n".join(problems)


def test_enum_members_match_the_model(upgrade_sql, metadata):
    """The drift SQLite cannot catch.

    Every test outside this file runs on SQLite, where an enum column is a
    plain VARCHAR that accepts any string — so a model enum can gain a member
    with no migration and the whole suite stays green until the first insert
    against Postgres.
    """

    in_migration = _enum_values_after_migrations(upgrade_sql)
    problems = []
    for name, expected in _model_enums(metadata).items():
        actual = set(in_migration.get(name, []))
        if actual != expected:
            problems.append(
                f"{name}: model has {sorted(expected)}, migration produces {sorted(actual)}"
            )
    assert not problems, "\n".join(problems)


def test_every_created_enum_is_dropped_on_downgrade(upgrade_sql, downgrade_sql):
    """Alembic autogenerate emits CREATE TYPE but never DROP TYPE, so without
    the hand-added block a downgrade followed by an upgrade fails."""

    created = set(re.findall(r"CREATE TYPE (\w+) AS ENUM", upgrade_sql))
    dropped = set(re.findall(r"DROP TYPE IF EXISTS (\w+)", downgrade_sql))
    assert created, "expected the migration to create enum types"
    assert created == dropped, f"unmatched: {sorted(created ^ dropped)}"


@pytest.mark.parametrize("child", ["deal_outcomes", "crm_activities", "notes"])
def test_tables_referencing_deals_are_ordered_correctly(upgrade_sql, downgrade_sql, child):
    """These gained FKs to deals.id, so `deals` must be created before them
    and dropped after them."""

    assert upgrade_sql.index("CREATE TABLE deals ") < upgrade_sql.index(f"CREATE TABLE {child} ")
    assert downgrade_sql.index(f"DROP TABLE {child}") < downgrade_sql.index("DROP TABLE deals")


def test_meetings_created_after_contacts(upgrade_sql):
    """meetings.contact_id references contacts.id."""

    assert upgrade_sql.index("CREATE TABLE contacts ") < upgrade_sql.index("CREATE TABLE meetings ")


def test_money_is_numeric_not_float(upgrade_sql):
    """Deal.amount is summed across a pipeline into revenue forecasts, so
    float error would compound per deal."""

    block = re.search(r"CREATE TABLE deals \((.*?)\n\);", upgrade_sql, re.S).group(1)
    assert re.search(r"amount NUMERIC\(14, ?2\)", block), block


def test_forecast_money_columns_are_numeric(upgrade_sql, metadata):
    """`revenue_forecasts.predicted_revenue` shipped as `Float` and was altered
    to NUMERIC in Module 12 — the column holds the sum of `Deal.amount` across
    a whole pipeline, so it must obey the same rule.

    Asserted against the model rather than parsed out of the DDL because the
    change arrives as an `ALTER COLUMN ... TYPE`, which the CREATE TABLE block
    does not reflect.
    """

    table = metadata.tables["revenue_forecasts"]
    for column in ("predicted_revenue", "committed_revenue", "weighted_pipeline"):
        assert isinstance(table.columns[column].type, sa.Numeric), column
        assert not isinstance(table.columns[column].type, sa.Float), column
    assert "ALTER COLUMN predicted_revenue TYPE NUMERIC" in upgrade_sql


def test_pgvector_extension_is_created_before_use(upgrade_sql):
    assert "CREATE EXTENSION IF NOT EXISTS vector" in upgrade_sql
    assert upgrade_sql.index("CREATE EXTENSION IF NOT EXISTS vector") < upgrade_sql.index(
        "CREATE TABLE knowledge_embeddings "
    )


def test_enums_persist_by_value_not_name(upgrade_sql):
    """The DB must hold `sales_executive`, matching the JWT claim, require_role,
    and the frontend — not SQLAlchemy's default `SALES_EXECUTIVE`."""

    assert "CREATE TYPE role AS ENUM ('admin', 'sales_manager', 'sales_executive', 'marketing')" in upgrade_sql
