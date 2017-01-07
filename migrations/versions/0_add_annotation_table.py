""" Add annotation table

Revision ID: 37043decf526
Create Date: 2017-01-07 16:31:53.248833

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '37043decf526'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'annotation',
        sa.Column('surrogate_id', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(), nullable=True),
        sa.Column('target', sa.String(), nullable=True),
        sa.Column('motivation', sa.String(), nullable=True),
        sa.Column('date', sa.DateTime(), nullable=True),
        sa.Column('annotation', postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint('surrogate_id'),
        sa.UniqueConstraint('id'))


def downgrade():
    op.drop_table('annotation')
