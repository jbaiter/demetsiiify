import shortuuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects import postgresql


db = SQLAlchemy()


class Manifest(db.Model):
    uuid = db.Column(db.String(22), primary_key=True)
    metsurl = db.Column(db.String, unique=True)
    manifest = db.Column(postgresql.JSONB)
    # TODO: Title (for use in collection view)

    def __init__(self, metsurl, manifest, uuid=None):
        self.uuid = uuid or shortuuid.uuid()
        self.metsurl = metsurl
        self.manifest = manifest


class IIIFImage(db.Model):
    uuid = db.Column(db.String(22), primary_key=True)
    info = db.Column(postgresql.JSONB)
    images = db.relationship('Image', backref='iiif_image', lazy='dynamic')

    def __init__(self, info, uuid=None):
        self.uuid = uuid or shortuuid.uuid()
        self.info = info


class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    url = db.Column(db.String, unique=True)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    format = db.Column(db.Text)
    iiif_uuid = db.Column(db.String(22), db.ForeignKey('iiif_image.uuid'))

    def __init__(self, url, width, height, format, iiif_uuid):
        self.url = url
        self.width = width
        self.height = height
        self.format = format
        self.iiif_uuid = iiif_uuid
