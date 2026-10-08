"""Student contracts: one e-signed training contract per enrollment

Revision ID: 5c2e9a71d4b3
Revises: 3b8e1d2c4f60
Create Date: 2026-10-08

"""
import sqlalchemy as sa
from alembic import op

revision = "5c2e9a71d4b3"
down_revision = "3b8e1d2c4f60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("cohort_id", sa.Integer(), nullable=True),
        sa.Column("contract_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("form_data", sa.JSON(), nullable=True),
        sa.Column("total_due", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_paid", sa.Numeric(12, 2), nullable=True),
        sa.Column("balance", sa.Numeric(12, 2), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("template_key", sa.String(length=500), nullable=True),
        sa.Column("file_key", sa.String(length=500), nullable=True),
        sa.Column("signature_key", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enrollment_id"),
        sa.UniqueConstraint("contract_number"),
    )
    op.create_index("ix_student_contracts_student_id", "student_contracts", ["student_id"])
    op.create_index("ix_student_contracts_course_id", "student_contracts", ["course_id"])
    op.create_index("ix_student_contracts_status", "student_contracts", ["status"])


def downgrade():
    op.drop_table("student_contracts")
