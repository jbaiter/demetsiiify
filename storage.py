import shortuuid
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects import postgresql as pg


db = SQLAlchemy()


class Manifest(db.Model):
    uuid = db.Column(db.String(22), primary_key=True)
    metsurl = db.Column(db.String, unique=True)
    manifest = db.Column(pg.JSONB)
    label = db.Column(db.String)

    def __init__(self, metsurl, manifest, label=None, uuid=None):
        self.uuid = uuid or shortuuid.uuid()
        self.metsurl = metsurl
        self.manifest = manifest
        self.label = label

    @classmethod
    def save(cls, *manifests):
        base_query = pg.insert(cls).returning(Manifest.uuid)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[Manifest.metsurl],
                set_=dict(manifest=base_query.excluded.manifest)),
            [dict(uuid=m.uuid, metsurl=m.metsurl,
                  manifest=m.manifest) for m in manifests])

    @classmethod
    def get(cls, uuid):
        return cls.query.get(uuid)

    @classmethod
    def by_metsurl(cls, metsurl):
        return cls.query.filter_by(metsurl=metsurl).first()

    @classmethod
    def get_sequence(cls, manifest_id, sequence_id):
        row = db.session.execute("""
            SELECT seqs
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs
            WHERE seqs->>'@id' LIKE '%' || :sequence_id || '.json';
        """, dict(sequence_id=sequence_id)).first()
        return row[0] if row else None

    @classmethod
    def get_canvas(cls, manifest_id, canvas_id):
        row = db.session.execute("""
            SELECT canvases
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs,
                 jsonb_array_elements(seqs->'canvases') canvases
            WHERE canvases->>'@id' LIKE '%' || :canvas_id || '.json';
        """, dict(canvas_id=canvas_id)).first()
        return row[0] if row else None

    @classmethod
    def get_image_annotation(cls, manifest_id, anno_id):
        row = db.session.execute("""
            SELECT images
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs,
                 jsonb_array_elements(seqs->'canvases') canvases,
                 jsonb_array_elements(canvases->'images') images
            WHERE images->>'@id' LIKE '%' || :anno_id || '.json';
        """, dict(anno_id=anno_id)).first()
        return row[0] if row else None

    @classmethod
    def get_range(cls, manifest_id, range_id):
        row = db.session.execute("""
            SELECT ranges
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'structures') structures,
            WHERE ranges->>'@id' LIKE '%' || :range_id || '.json';
        """, dict(range_id=range_id)).first()
        return row[0] if row else None


class IIIFImage(db.Model):
    uuid = db.Column(db.String(22), primary_key=True)
    info = db.Column(pg.JSONB)
    images = db.relationship('Image', backref='iiif_image', lazy='dynamic')

    def __init__(self, info, uuid=None):
        self.uuid = uuid or shortuuid.uuid()
        self.info = info

    def get_image_url(self, format_, width=None, height=None):
        query = {'format': format_}
        if width:
            query['width'] = width
        if height:
            query['height'] = height
        query = self.images.filter_by(**query)
        if width is None and height is None:
            query = query.order_by(Image.width.desc())
        image = query.first()
        return image.url if image else None

    @classmethod
    def get(cls, uuid):
        return cls.query.get(uuid)

    @classmethod
    def save(cls, *images):
        base_query = pg.insert(cls).returning(IIIFImage.uuid)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[IIIFImage.uuid],
                set_=dict(info=base_query.excluded.info)),
            [dict(uuid=i.uuid, info=i.info) for i in images])

    @classmethod
    def delete_orphaned(cls):
        """ Delete all images that do not appear in any manifest. """
        return db.session.execute(
            """
            WITH image_ids AS (
              SELECT c#>>'{images,0,resource,service,@id}' as id
              FROM manifest m,
                   jsonb_array_elements(
                     m.manifest#>'{sequences,0,canvases}') c)
            DELETE FROM iiif_image
            WHERE (SELECT count(*)
                   FROM image_ids
                   WHERE id LIKE '%' || uuid) = 0
            RETURNING info;
            """)


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

    @classmethod
    def get(cls, id_):
        return cls.query.get(id_)

    @classmethod
    def by_url(cls, url):
        return cls.query.filter_by(url=url).first()

    @classmethod
    def save(cls, *images):
        base_query = pg.insert(cls).returning(Image.id)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[Image.url],
                set_=dict(width=base_query.excluded.width,
                          height=base_query.excluded.height,
                          format=base_query.excluded.format,
                          iiif_uuid=base_query.excluded.iiif_uuid)),
            [dict(url=i.url, width=i.width, height=i.height,
                  format=i.format, iiif_uuid=i.iiif_uuid) for i in images])
