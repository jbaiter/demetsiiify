"""Background tasks."""
import time
from collections import deque
from pathlib import Path
from typing import Deque, Optional

import lxml.etree as ET
import requests
from flask import current_app, g
from rq import get_current_job, Job

from . import make_queues, make_redis
from .iiif import make_manifest
from .imgfetch import add_image_dimensions, ImageDownloadError
from .mets import MetsDocument
from .models import (db, Manifest, IIIFImage, Image as DbImage,
                     Identifier, Collection)
from .oai import OaiRepository


def get_redis():
    """Get the global redis singleton."""
    if not hasattr(g, 'redis'):
        g.redis = make_redis()
    return g.redis


#: Queue singletons
queue, oai_queue = make_queues(get_redis(), 'tasks', 'oai_imports')


def fetch_image_dimensions(doc: MetsDocument, job: Optional[Job] = None,
                           concurrency: int = 2) -> None:
    """Fetch missing image dimensions and report on progress."""
    times: Deque[float] = deque(maxlen=50)
    start_time = time.time()
    for idx, total in add_image_dimensions(
            doc.files.values(), jpeg_only=True, concurrency=concurrency):
        duration = time.time() - start_time
        times.append(duration)
        if job:
            eta = (sum(times) / len(times)) * (total - idx)
            job.meta.update(dict(current_image=idx, total_images=total,
                                 eta=eta))
            job.save()
        start_time = time.time()


def import_mets_job(mets_url: str, collection_id: Optional[str] = None,
                    concurrency: int = 2) -> str:
    """Import job."""
    job = get_current_job()
    about_url = "{}://{}/about".format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'])
    try:
        xml = requests.get(mets_url, allow_redirects=True).content
        tree = ET.fromstring(xml)
        doc = MetsDocument(tree, url=mets_url)
        if current_app.config['DUMP_METS']:
            xml_path = (Path(current_app.config['DUMP_METS']) /
                        (doc.primary_id.replace('/', '_') + ".xml"))
            with xml_path.open('wb') as fp:
                fp.write(ET.tostring(tree, pretty_print=True))

        # Fetch known image dimensions from database
        for file in doc.files.values():
            db_info = DbImage.by_url(file.url)
            if db_info is None:
                continue
            file.width = db_info.width
            file.height = db_info.height
            file.mimetype = db_info.mimetype
        try:
            fetch_image_dimensions(doc, job, concurrency)
        except Exception as e:
            # Write images that could be read to database, as to avoid
            # a costly re-scrape when the bug(?) gets fixed
            db_images = [DbImage(f.url, f.width, f.height, f.mimetype)
                         for f in doc.files.values()
                         if f.width is not None and f.height is not None]
            DbImage.save(*db_images)
            db.session.commit()
            raise e
        if not doc.files:
            raise ImageDownloadError(
                "METS at {} does not reference any JPEG images"
                .format(mets_url))

        existing_manifest = Manifest.by_origin(mets_url)
        if existing_manifest:
            manifest_id = existing_manifest.id
        else:
            manifest_id = doc.primary_id
        base_url = "{}://{}".format(
            current_app.config['PREFERRED_URL_SCHEME'],
            current_app.config['SERVER_NAME'])
        manifest = make_manifest(manifest_id, doc, base_url=base_url)
        db_manifest = Manifest(mets_url, manifest, id=manifest_id,
                               label=manifest['label'])
        Manifest.save(db_manifest)
        db_manifest = Manifest.get(db_manifest.id)
        identifiers = [Identifier(id_, type, db_manifest.id)
                       for type, id_ in doc.identifiers.items()]
        if identifiers:
            Identifier.save(*identifiers)
        if collection_id:
            collection = Collection.get(collection_id)
            if collection is None:
                raise ValueError("Could not find collection with id {}"
                                 .format(collection_id))
            collection.manifests.append(db_manifest)

        # Since the METS might have already been indexed, there's the
        # possibility that the IIIF images might have changed, leading to
        # orphaned images.
        IIIFImage.delete_orphaned()
        db.session.commit()
        return manifest['@id']
    except Exception as e:
        db.session.rollback()
        raise e


def import_from_oai(oai_endpoint, since=None):
    """Import new METS documents from an OAI endpoint."""
    repo = oai.OaiRepository(oai_endpoint)
    sets = dict(repo.list_sets())

    for mets_url, set_id in repo.list_record_urls(since=since,
                                                  include_sets=True):
        if set_id is not None:
            collection = Collection.get(set_id)
            if collection is None:
                collection = Collection(set_id, sets[set_id])
                Collection.save(collection)
                db.session.commit()
        oai_queue.enqueue(import_mets_job, mets_url, set_id)
