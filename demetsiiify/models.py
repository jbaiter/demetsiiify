from datetime import datetime

import shortuuid
from flask import current_app, url_for
from sqlalchemy.dialects import postgresql as pg

from .extensions import db


class Identifier(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True, nullable=False)
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
            base_query.on_conflict_do_nothing(),
            [dict(id=i.id, type=i.type, manifest_id=i.manifest_id)
             for i in identifiers])

    @classmethod
    def resolve(cls, identifier):
        result = cls.query.filter_by(id=identifier).first()
        if result:
            return result.manifest_id


class Manifest(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True, nullable=False)
    identifiers = db.relationship('Identifier', backref='manifest',
                                  lazy='dynamic')
    origin = db.Column(db.String, unique=True, nullable=False)
    manifest = db.Column(pg.JSONB, nullable=False)
    label = db.Column(db.String, nullable=False)

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
                index_elements=[Manifest.id],
                set_=dict(manifest=base_query.excluded.manifest)),
            [dict(id=m.id, origin=m.origin, label=m.label,
                  manifest=m.manifest) for m in manifests])

    @classmethod
    def get_latest(cls, num=10):
        return cls.query.limit(num).all()

    @classmethod
    def get(cls, id):
        manifest = cls.query.filter_by(id=id).first()
        collections = [
            ('index',
            "All manifests available at {}".format(
                current_app.config['SERVER_NAME']))]
        collections.extend([
            (c.id, c.label)
            for c in manifest.collections.options(db.load_only('id')).all()])
        manifest.manifest['within'] = [
            {'@id': url_for('iiif.get_collection', collection_id=cid,
                            page_id='top', _external=True),
             'label': clabel,
             '@type': 'sc:Collection'} for cid, clabel in collections]
        return manifest

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
    id = db.Column(db.String, unique=True, nullable=False)
    info = db.Column(pg.JSONB, nullable=False)
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
    url = db.Column(db.String, unique=True, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    format = db.Column(db.Text, nullable=False)
    iiif_id = db.Column(db.String(22), db.ForeignKey('iiif_image.id'),
                        nullable=True)

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


class Annotation(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True, nullable=False)
    target = db.Column(db.String, nullable=False)
    motivation = db.Column(db.String, nullable=False)
    date = db.Column(db.DateTime)
    annotation = db.Column(pg.JSONB, nullable=False)

    def __init__(self, annotation):
        self.id = annotation['@id'].split('/')[-1]
        self.target = self._extract_target(annotation['on'])
        self.motivation = annotation['motivation']
        self.date = datetime.now()
        self.annotation = annotation

    def _extract_target(self, on):
        if isinstance(on, str):
            return on.split('#')[0]
        elif on['@type'] == 'oa:SpecificResource':
            return on['full']
        else:
            raise ValueError("Cannot deal with on={}".format(on))

    @classmethod
    def get(cls, id_):
        return cls.query.filter_by(id=id_).first()

    @classmethod
    def delete(cls, *annotations):
        for anno in annotations:
            db.session.delete(anno)
        db.session.flush()

    @classmethod
    def save(cls, *annotations):
        base_query = pg.insert(cls).returning(Annotation.id)
        return db.session.execute(
            base_query.on_conflict_do_update(
                index_elements=[Annotation.id],
                set_=dict(annotation=base_query.excluded.annotation,
                          target=base_query.excluded.target,
                          motivation=base_query.excluded.motivation,
                          date=datetime.now())),
            [dict(id=a.id, target=a.target, motivation=a.motivation,
                  date=a.date, annotation=a.annotation) for a in annotations])

    @classmethod
    def search(cls, target=None, motivation=None, date_ranges=None):
        filter_args = {}
        if target:
            filter_args['target'] = target
        if motivation:
            filter_args['motivation'] = motivation
        query = cls.query.filter_by(**filter_args)
        if date_ranges:
            query = query.filter(db.or_(
                *[Annotation.date.between(start, end)
                  for start, end in date_ranges]))
        return query


collection_manifest_table = db.Table(
    'collection_manifest',
    db.Column('collection_id', db.Integer,
              db.ForeignKey('collection.surrogate_id'),
              nullable=False),
    db.Column('manifest_id', db.Integer,
              db.ForeignKey('manifest.surrogate_id'),
              nullable=False))


class Collection(db.Model):
    surrogate_id = db.Column(db.Integer, primary_key=True)
    id = db.Column(db.String, unique=True, nullable=False)
    label = db.Column(db.String, nullable=False)
    manifests = db.relationship(
        'Manifest', secondary=collection_manifest_table,
        backref=db.backref('collections', lazy='dynamic'),
        lazy='dynamic')
    parent_collection_id = db.Column(
        db.String, db.ForeignKey('collection.id'))
    parent_collection = db.relationship(
        'Collection', backref=db.backref('child_collections', lazy='dynamic'),
        remote_side='Collection.id')

    def __init__(self, identifier, name):
        self.label = name
        self.id = identifier

    @classmethod
    def save(cls, *collections):
        base_query = pg.insert(cls).returning(Collection.id)
        return db.session.execute(
            base_query.on_conflict_do_nothing(),
            [dict(id=c.id, label=c.label) for c in collections])

    @classmethod
    def get(cls, id):
        return cls.query.filter_by(id=id).first()


class OaiRepository(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String, unique=True, nullable=False)
    name = db.Column(db.String, nullable=False)
    last_update = db.DateTime()

    def __init__(self, endpoint, name):
        self.endpoint = endpoint
        self.name = name
