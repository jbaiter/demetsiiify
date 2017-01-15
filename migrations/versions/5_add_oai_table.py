""" Add table for OAI repositories

Revision ID: 71874271208e
Revises: a80b4f777c12
Create Date: 2017-01-15 21:47:58.946488

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '71874271208e'
down_revision = 'a80b4f777c12'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'oai_repository',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'))


def downgrade():
    op.drop_table('oai_repository')
