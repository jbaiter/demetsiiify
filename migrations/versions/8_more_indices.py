""" Add more indices

Revision ID: cd5abd425969
Revises: 58cbc3838dcd
Create Date: 2017-01-21 13:45:03.203309

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'cd5abd425969'
down_revision = '58cbc3838dcd'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f('ix_annotation_target'),
                    'annotation', ['target'], unique=False)
    op.create_index(op.f('ix_collection_manifest_collection_id'),
                    'collection_manifest', ['collection_id'], unique=False)
    op.create_index(op.f('ix_collection_manifest_manifest_id'),
                    'collection_manifest', ['manifest_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_collection_manifest_manifest_id'),
                  table_name='collection_manifest')
    op.drop_index(op.f('ix_collection_manifest_collection_id'),
                  table_name='collection_manifest')
    op.drop_index(op.f('ix_annotation_target'), table_name='annotation')
