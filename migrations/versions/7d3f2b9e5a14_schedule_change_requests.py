"""Teacher schedule-change (class handover) requests

Revision ID: 7d3f2b9e5a14
Revises: 5c2e9a71d4b3
Create Date: 2026-10-13

"""
import sqlalchemy as sa
from alembic import op

revision = "7d3f2b9e5a14"
down_revision = "5c2e9a71d4b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schedule_change_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("class_session_id", sa.Integer(), nullable=False),
        sa.Column("sender_teacher_id", sa.Integer(), nullable=False),
        sa.Column("recipient_teacher_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_teacher_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("sender_teacher_id <> recipient_teacher_id",
                           name="ck_schedule_change_distinct_teachers"),
        sa.ForeignKeyConstraint(["class_session_id"], ["class_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_teacher_id"], ["teachers.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("class_session_id", "sender_teacher_id", "recipient_teacher_id", "status"):
        op.create_index(f"ix_schedule_change_requests_{column}", "schedule_change_requests",
                        [column])
    op.create_index("uq_schedule_change_pending", "schedule_change_requests",
                    ["class_session_id"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index("uq_schedule_change_accepted", "schedule_change_requests",
                    ["class_session_id"], unique=True,
                    postgresql_where=sa.text("status = 'accepted'"))


def downgrade():
    op.drop_table("schedule_change_requests")
