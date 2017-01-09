""" Add collections table

Revision ID: 4502e3e98b84
Revises: 37043decf526
Create Date: 2017-01-08 21:34:07.708779

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4502e3e98b84'
down_revision = '37043decf526'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'collection',
        sa.Column('surrogate_id', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(), nullable=True),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('parent_collection_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['parent_collection_id'], ['collection.id']),
        sa.PrimaryKeyConstraint('surrogate_id'),
        sa.UniqueConstraint('id'))

    op.create_table(
        'collection_manifest',
        sa.Column('collection_id', sa.Integer(), nullable=True),
        sa.Column('manifest_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['collection_id'],
            ['collection.surrogate_id']),
        sa.ForeignKeyConstraint(
            ['manifest_id'],
            ['manifest.surrogate_id']))


def downgrade():
    op.drop_table('collection_manifest')
    op.drop_table('collection')
