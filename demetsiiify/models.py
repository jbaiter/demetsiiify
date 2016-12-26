import shortuuid
from sqlalchemy.dialects import postgresql as pg

from .extensions import db


class Identifier(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True)
    type = db.Column(db.String)
    manifest_id = db.Column(db.String, db.ForeignKey('manifest.id'),
                            nullable=False)

    def __init__(self, id, type_, manifest_id):
        self.id = id
        self.type = type_
        self.manifest_id = manifest_id

    @classmethod
    def save(cls, *identifiers):
        base_query = pg.insert(cls).returning(Identifier.id)
        return db.session.execute(
            base_query.on_conflict_do_nothing(
                index_elements=[Identifier.id]),
            [dict(id=i.id, type=i.type, manifest_id=i.manifest_id)
             for i in identifiers])

    @classmethod
    def resolve(cls, identifier):
        result = cls.query.filter_by(id=identifier).first()
        if result:
            return result.manifest_id


class Manifest(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True)
    identifiers = db.relationship('Identifier', backref='manifest',
                                  lazy='dynamic')
    origin = db.Column(db.String, unique=True)
    manifest = db.Column(pg.JSONB)
    label = db.Column(db.String)

    def __init__(self, origin, manifest, label=None, id=None):
        self.id = id or shortuuid.uuid()
        self.origin = origin
        self.manifest = manifest
        self.label = label

    @classmethod
    def save(cls, *manifests):
        base_query = pg.insert(cls).returning(Manifest.id)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[Manifest.origin],
                set_=dict(manifest=base_query.excluded.manifest)),
            [dict(id=m.id, origin=m.origin,
                  manifest=m.manifest) for m in manifests])

    @classmethod
    def get(cls, id):
        return cls.query.filter_by(id=id).first()

    @classmethod
    def by_origin(cls, origin):
        return cls.query.filter_by(origin=origin).first()

    @classmethod
    def get_sequence(cls, manifest_id, sequence_id):
        row = db.session.execute("""
            SELECT seqs
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs
            WHERE m.id = :manifest_id
                  AND seqs->>'@id' LIKE '%' || :sequence_id || '.json';
        """, dict(manifest_id=manifest_id, sequence_id=sequence_id)).first()
        return row[0] if row else None

    @classmethod
    def get_canvas(cls, manifest_id, canvas_id):
        row = db.session.execute("""
            SELECT canvases
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs,
                 jsonb_array_elements(seqs->'canvases') canvases
            WHERE m.id = :manifest_id
                  AND canvases->>'@id' LIKE '%' || :canvas_id || '.json';
        """, dict(manifest_id=manifest_id, canvas_id=canvas_id)).first()
        return row[0] if row else None

    @classmethod
    def get_image_annotation(cls, manifest_id, anno_id):
        row = db.session.execute("""
            SELECT images
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'sequences') seqs,
                 jsonb_array_elements(seqs->'canvases') canvases,
                 jsonb_array_elements(canvases->'images') images
            WHERE m.id = :manifest_id
                  AND images->>'@id' LIKE '%' || :anno_id || '.json';
        """, dict(manifest_id=manifest_id, anno_id=anno_id)).first()
        return row[0] if row else None

    @classmethod
    def get_range(cls, manifest_id, range_id):
        row = db.session.execute("""
            SELECT ranges
            FROM manifest m,
                 jsonb_array_elements(m.manifest->'structures') structures,
            WHERE m.id = :manifest_id
                  AND ranges->>'@id' LIKE '%' || :range_id || '.json';
        """, dict(manifest_id=manifest_id, range_id=range_id)).first()
        return row[0] if row else None


class IIIFImage(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True)
    info = db.Column(pg.JSONB)
    images = db.relationship('Image', backref='iiif_image', lazy='dynamic')

    def __init__(self, info, id=None):
        self.id = id or shortuuid.uuid()
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
    def get(cls, id):
        return cls.query.filter_by(id=id).first()

    @classmethod
    def save(cls, *images):
        base_query = pg.insert(cls).returning(IIIFImage.id)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[IIIFImage.id],
                set_=dict(info=base_query.excluded.info)),
            [dict(id=i.id, info=i.info) for i in images])

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
                   WHERE id LIKE '%' || id) = 0
            RETURNING info;
            """)


class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String, unique=True)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    format = db.Column(db.Text)
    iiif_id = db.Column(db.String(22), db.ForeignKey('iiif_image.id'))

    def __init__(self, url, width, height, format, iiif_id=None):
        self.url = url
        self.width = width
        self.height = height
        self.format = format
        if iiif_id:
            self.iiif_id = iiif_id

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
                          iiif_id=base_query.excluded.iiif_id)),
            [dict(url=i.url, width=i.width, height=i.height,
                  format=i.format, iiif_id=i.iiif_id) for i in images])
