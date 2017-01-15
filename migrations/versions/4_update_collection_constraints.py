""" Update NULL constraints on collection tables

Revision ID: a80b4f777c12
Revises: b7ef2a9c2e54
Create Date: 2017-01-15 21:45:33.959203

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a80b4f777c12'
down_revision = 'b7ef2a9c2e54'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('collection', 'id',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('collection', 'label',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.alter_column('collection_manifest', 'collection_id',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.alter_column('collection_manifest', 'manifest_id',
               existing_type=sa.INTEGER(),
               nullable=False)


def downgrade():
    op.alter_column('collection_manifest', 'manifest_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('collection_manifest', 'collection_id',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('collection', 'label',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.alter_column('collection', 'id',
               existing_type=sa.VARCHAR(),
               nullable=True)
