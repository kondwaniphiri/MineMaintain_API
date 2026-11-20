"""Create user accounts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

roles = postgresql.ENUM(
    "OPERATOR",
    "TECHNICIAN",
    "SUPERVISOR",
    "ADMINISTRATOR",
    name="user_role",
    create_type=False,
)


def upgrade() -> None:
    roles.create(op.get_bind())
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(roles), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND email <> ''", name="ck_users_email"
        ),
        sa.CheckConstraint(
            "cardinality(roles) > 0 AND array_position(roles, NULL) IS NULL",
            name="ck_users_roles",
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
    roles.drop(op.get_bind())
