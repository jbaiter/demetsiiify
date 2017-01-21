""" Add index on Image.iiif_id

Revision ID: 58cbc3838dcd
Revises: f7a7c1283217
Create Date: 2017-01-21 09:07:08.591894

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '58cbc3838dcd'
down_revision = 'f7a7c1283217'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f('ix_image_iiif_id'), 'image', ['iiif_id'],
                    unique=False)


def downgrade():
    op.drop_index(op.f('ix_image_iiif_id'), table_name='image')
