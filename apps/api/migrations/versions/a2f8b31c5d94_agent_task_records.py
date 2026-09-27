"""agent task records: status, error, timings, run correlation

Phase 9 Module 3. `ai_interaction_logs` recorded only successful agent calls —
the log line was written after the agent returned, so a raising agent left
nothing behind and the one table built for auditing what an agent was given was
blind to the failure case.

Adds the fields the module brief's section 8 requires and this table lacked:

  * `status` / `error` — a failed attempt is now a row, not a silence.
  * `started_at` / `completed_at` / `duration_ms` — stored rather than derived
    from `created_at`, which is the database clock while the rest are the
    application's.
  * `run_id` / `workflow` / `step` / `job_id` — correlate the steps of one
    execution, so replaying a run is a query rather than a guess from
    timestamps.
  * `attempt` — a task that succeeded on its third try is otherwise
    indistinguishable from one that succeeded immediately.

`output_payload` becomes nullable: a failed attempt has no output, and writing
`{}` would make "returned nothing" indistinguishable from "did not run".

The `agenttaskstatus` enum is dropped explicitly on downgrade — autogenerate
emits CREATE TYPE but never the matching DROP, so without it a downgrade
followed by an upgrade fails with 'type already exists'.

Revision ID: a2f8b31c5d94
Revises: f4d2a7c1e806
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a2f8b31c5d94'
down_revision: Union[str, None] = 'f4d2a7c1e806'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'ai_interaction_logs'


def upgrade() -> None:
    op.add_column(TABLE, sa.Column('run_id', sa.UUID(), nullable=True))
    op.add_column(TABLE, sa.Column('workflow', sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column('step', sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column('job_id', sa.UUID(), nullable=True))
    # Created explicitly. `op.add_column` with an Enum emits the column but
    # NOT the type, so without this the migration fails on Postgres with
    # 'type "agenttaskstatus" does not exist' — `create_type=False` then stops
    # SQLAlchemy trying to create it a second time.
    op.execute("CREATE TYPE agenttaskstatus AS ENUM ('completed', 'failed')")
    op.add_column(
        TABLE,
        sa.Column(
            'status',
            postgresql.ENUM('completed', 'failed', name='agenttaskstatus', create_type=False),
            nullable=False,
            # Existing rows are all successes by construction: the old code
            # could only write a row after an agent returned.
            server_default='completed',
        ),
    )
    op.alter_column(TABLE, 'status', server_default=None)
    op.add_column(TABLE, sa.Column('error', sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'))
    op.alter_column(TABLE, 'attempt', server_default=None)
    op.add_column(TABLE, sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column('duration_ms', sa.Integer(), nullable=True))

    op.alter_column(TABLE, 'output_payload', existing_type=sa.JSON(), nullable=True)

    op.create_foreign_key(None, TABLE, 'jobs', ['job_id'], ['id'])
    op.create_index(op.f('ix_ai_interaction_logs_run_id'), TABLE, ['run_id'], unique=False)
    op.create_index(op.f('ix_ai_interaction_logs_job_id'), TABLE, ['job_id'], unique=False)
    op.create_index(op.f('ix_ai_interaction_logs_status'), TABLE, ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_interaction_logs_status'), table_name=TABLE)
    op.drop_index(op.f('ix_ai_interaction_logs_job_id'), table_name=TABLE)
    op.drop_index(op.f('ix_ai_interaction_logs_run_id'), table_name=TABLE)

    # Rows recording a failure have no output; the column is NOT NULL again
    # after this, so they cannot be kept.
    op.execute(f"DELETE FROM {TABLE} WHERE output_payload IS NULL")
    op.alter_column(TABLE, 'output_payload', existing_type=sa.JSON(), nullable=False)

    for column in (
        'duration_ms',
        'completed_at',
        'started_at',
        'attempt',
        'error',
        'status',
        'job_id',
        'step',
        'workflow',
        'run_id',
    ):
        op.drop_column(TABLE, column)
    op.execute('DROP TYPE IF EXISTS agenttaskstatus')
