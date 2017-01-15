""" Add last_update column to OAI table

Revision ID: f7a7c1283217
Revises: 71874271208e
Create Date: 2017-01-15 22:35:21.478807

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a7c1283217'
down_revision = '71874271208e'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('oai_repository',
                  sa.Column('last_update', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('oai_repository', 'last_update')
