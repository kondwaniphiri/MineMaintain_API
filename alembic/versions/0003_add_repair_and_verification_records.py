"""Add repair and verification records"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "labour_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("minutes > 0", name="labour_positive_minutes"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["labour_entries.id"],
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_id"),
    )
    op.create_index(
        op.f("ix_labour_entries_order_id"), "labour_entries", ["order_id"], unique=False
    )
    op.create_table(
        "part_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("part_code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0 AND quantity < 'Infinity'::numeric",
            name="parts_positive_quantity",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["part_usage.id"],
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_id"),
    )
    op.create_index(
        op.f("ix_part_usage_order_id"), "part_usage", ["order_id"], unique=False
    )
    op.create_table(
        "repair_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("repair_summary", sa.Text(), nullable=False),
        sa.Column("test_results", sa.Text(), nullable=False),
        sa.Column("external_reference", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_unique_constraint(
        "uq_submission_order_version",
        "repair_submissions",
        ["order_id", "order_version"],
    )
    op.create_index(
        op.f("ix_repair_submissions_order_id"),
        "repair_submissions",
        ["order_id"],
        unique=False,
    )
    op.create_table(
        "verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("verifier_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "ACCEPT",
                "REJECT",
                name="verification_decision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["repair_submissions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["verifier_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id"),
    )
    op.create_index(
        op.f("ix_verifications_order_id"), "verifications", ["order_id"], unique=False
    )
    op.add_column("work_notes", sa.Column("supersedes_id", sa.Uuid(), nullable=True))
    op.add_column(
        "work_notes", sa.Column("correction_reason", sa.Text(), nullable=True)
    )
    op.create_unique_constraint(
        "work_notes_supersedes_id_key", "work_notes", ["supersedes_id"]
    )
    op.create_foreign_key(
        "work_notes_supersedes_id_fkey",
        "work_notes",
        "work_notes",
        ["supersedes_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "work_notes_supersedes_id_fkey", "work_notes", type_="foreignkey"
    )
    op.drop_constraint("work_notes_supersedes_id_key", "work_notes", type_="unique")
    op.drop_column("work_notes", "correction_reason")
    op.drop_column("work_notes", "supersedes_id")
    op.drop_index(op.f("ix_verifications_order_id"), table_name="verifications")
    op.drop_table("verifications")
    op.drop_index(
        op.f("ix_repair_submissions_order_id"), table_name="repair_submissions"
    )
    op.drop_table("repair_submissions")
    op.drop_index(op.f("ix_part_usage_order_id"), table_name="part_usage")
    op.drop_table("part_usage")
    op.drop_index(op.f("ix_labour_entries_order_id"), table_name="labour_entries")
    op.drop_table("labour_entries")
