""" Update NULL constraints

Revision ID: b7ef2a9c2e54
Revises: 4502e3e98b84
Create Date: 2017-01-10 18:47:20.544943

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b7ef2a9c2e54'
down_revision = '4502e3e98b84'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'annotation', 'annotation',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False)
    op.alter_column(
        'annotation', 'id',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'annotation', 'motivation',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'annotation', 'target',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'identifier', 'id',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'iiif_image', 'id',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'iiif_image', 'info',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False)
    op.alter_column(
        'image', 'format',
        existing_type=sa.TEXT(),
        nullable=False)
    op.alter_column(
        'image', 'height',
        existing_type=sa.INTEGER(),
        nullable=False)
    op.alter_column(
        'image', 'url',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'image', 'width',
        existing_type=sa.INTEGER(),
        nullable=False)
    op.alter_column(
        'manifest', 'id',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'manifest', 'label',
        existing_type=sa.VARCHAR(),
        nullable=False)
    op.alter_column(
        'manifest', 'manifest',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False)
    op.alter_column(
        'manifest', 'origin',
        existing_type=sa.VARCHAR(),
        nullable=False)


def downgrade():
    op.alter_column(
        'manifest', 'origin',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'manifest', 'manifest',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True)
    op.alter_column(
        'manifest', 'label',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'manifest', 'id',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'image', 'width',
        existing_type=sa.INTEGER(),
        nullable=True)
    op.alter_column(
        'image', 'url',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'image', 'height',
        existing_type=sa.INTEGER(),
        nullable=True)
    op.alter_column(
        'image', 'format',
        existing_type=sa.TEXT(),
        nullable=True)
    op.alter_column(
        'iiif_image', 'info',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True)
    op.alter_column(
        'iiif_image', 'id',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'identifier', 'id',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'annotation', 'target',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'annotation', 'motivation',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'annotation', 'id',
        existing_type=sa.VARCHAR(),
        nullable=True)
    op.alter_column(
        'annotation', 'annotation',
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True)
