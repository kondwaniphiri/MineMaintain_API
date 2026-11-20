"""Add core maintenance workflow"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_table(
        "locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=160), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("manufacturer", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("serial", sa.String(length=160), nullable=True),
        sa.Column(
            "lifecycle",
            sa.Enum(
                "ACTIVE",
                "RETIRED",
                name="asset_lifecycle",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_code"),
    )
    op.create_index(
        op.f("ix_assets_location_id"), "assets", ["location_id"], unique=False
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_entity_timestamp",
        "audit_events",
        ["entity_type", "entity_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("route", sa.String(length=160), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column(
            "response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "route", "key"),
    )
    op.create_index(
        op.f("ix_idempotency_records_expires_at"),
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "fault_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("symptoms", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "suggested_priority",
            sa.Enum(
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                name="suggested_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "reviewed_priority",
            sa.Enum(
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                name="reviewed_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "SUBMITTED",
                "CONVERTED",
                "DISMISSED",
                name="fault_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="SUBMITTED",
            nullable=False,
        ),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column("related_report_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["related_report_id"],
            ["fault_reports.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fault_reports_asset_status",
        "fault_reports",
        ["asset_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fault_reports_reporter_id"),
        "fault_reports",
        ["reporter_id"],
        unique=False,
    )
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=35), nullable=False),
        sa.Column("fault_report_id", sa.Uuid(), nullable=False),
        sa.Column(
            "priority",
            sa.Enum(
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
                name="work_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "ASSIGNED",
                "IN_PROGRESS",
                "AWAITING_PARTS",
                "AWAITING_VERIFICATION",
                "CLOSED",
                "CANCELLED",
                name="work_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["fault_report_id"],
            ["fault_reports.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fault_report_id"),
        sa.UniqueConstraint("order_number"),
    )
    op.create_index(
        op.f("ix_work_orders_assigned_to"), "work_orders", ["assigned_to"], unique=False
    )
    op.create_index(
        op.f("ix_work_orders_due_at"), "work_orders", ["due_at"], unique=False
    )
    op.create_index(
        op.f("ix_work_orders_status"), "work_orders", ["status"], unique=False
    )
    op.create_table(
        "assignment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["from_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["to_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assignment_events_order_id"),
        "assignment_events",
        ["order_id"],
        unique=False,
    )
    op.create_table(
        "work_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "PROGRESS",
                "DIAGNOSIS",
                "REPAIR",
                "TEST",
                name="work_note_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["work_orders.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_work_notes_order_id"), "work_notes", ["order_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_work_notes_order_id"), table_name="work_notes")
    op.drop_table("work_notes")
    op.drop_index(op.f("ix_assignment_events_order_id"), table_name="assignment_events")
    op.drop_table("assignment_events")
    op.drop_index(op.f("ix_work_orders_status"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_due_at"), table_name="work_orders")
    op.drop_index(op.f("ix_work_orders_assigned_to"), table_name="work_orders")
    op.drop_table("work_orders")
    op.drop_index(op.f("ix_fault_reports_reporter_id"), table_name="fault_reports")
    op.drop_index("ix_fault_reports_asset_status", table_name="fault_reports")
    op.drop_table("fault_reports")
    op.drop_index(
        op.f("ix_idempotency_records_expires_at"), table_name="idempotency_records"
    )
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_entity_timestamp", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_assets_location_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_table("locations")
    op.drop_column("users", "version")
