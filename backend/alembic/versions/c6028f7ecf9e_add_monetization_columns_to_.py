"""Add monetization columns and project multi-tenancy

Revision ID: c6028f7ecf9e
Revises:
Create Date: 2026-04-15 08:14:02.358353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c6028f7ecf9e'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Handle Enums safely
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'subscriptionplan') THEN CREATE TYPE subscriptionplan AS ENUM ('FREE', 'TRIAL', 'PRO', 'ENTERPRISE'); END IF; END $$;")

    # 2. Add columns to organizations
    op.add_column('organizations', sa.Column('subscription_plan', sa.Enum('FREE', 'TRIAL', 'PRO', 'ENTERPRISE', name='subscriptionplan'), server_default='FREE', nullable=False))
    op.add_column('organizations', sa.Column('token_balance', sa.Integer(), server_default='1000', nullable=False))
    op.add_column('organizations', sa.Column('subscription_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('subscription_custom_limits', sa.JSON(), nullable=True))
    op.add_column('organizations', sa.Column('trial_starts_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('organizations', sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True))

    # 3. Add organization_id to projects for multi-tenancy
    op.add_column('projects', sa.Column('organization_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_projects_organization_id', 'projects', 'organizations', ['organization_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_projects_organization_id'), 'projects', ['organization_id'], unique=False)

    # 4. Handle UserRole enum update for ORG_ADMIN
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'org_admin'")


def downgrade() -> None:
    op.drop_index(op.f('ix_projects_organization_id'), table_name='projects')
    op.drop_constraint('fk_projects_organization_id', 'projects', type_='foreignkey')
    op.drop_column('projects', 'organization_id')
    op.drop_column('organizations', 'trial_ends_at')
    op.drop_column('organizations', 'trial_starts_at')
    op.drop_column('organizations', 'subscription_custom_limits')
    op.drop_column('organizations', 'subscription_expires_at')
    op.drop_column('organizations', 'token_balance')
    op.drop_column('organizations', 'subscription_plan')
