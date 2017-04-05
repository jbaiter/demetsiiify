import os.path
import smtplib
import time
from collections import deque, OrderedDict
from email.message import EmailMessage

import lxml.etree as ET
import requests
import shortuuid
from flask import current_app, g, url_for
from rq import get_current_job

from . import mets
from . import oai
from . import iiif
from . import make_queues, make_redis
from .models import db, Manifest, IIIFImage, Image, Identifier, Collection


EMAIL_TEMPLATE = """
The IIIF manifests for your METS files are now available for viewing at the
following addresses:

{}
"""


def get_redis():
    if not hasattr(g, 'redis'):
        g.redis = make_redis()
    return g.redis


queue, oai_queue = make_queues(get_redis(), 'tasks', 'oai_imports')


def _read_files(doc, job=None, concurrency=None):
    times = deque(maxlen=50)
    start_time = time.time()
    for idx, total in doc.read_files(jpeg_only=True, yield_progress=True,
                                     concurrency=concurrency):
        duration = time.time() - start_time
        times.append(duration)
        if job:
            job.meta.update(dict(
                current_image=idx,
                total_images=total,
                eta=(sum(times)/len(times)) * (total - idx)))
            job.save()
        start_time = time.time()


def _make_image_maps(doc):
    iiif_map = OrderedDict()
    thumbs_map = {}
    for phys_id, itm in doc.physical_items.items():
        image_ident = shortuuid.uuid()
        largest_image = max(itm.files, key=lambda f: f.height)
        smallest_image = min(itm.files, key=lambda f: f.height)
        iiif_info = iiif.make_info_data(
            image_ident, [(f.width, f.height) for f in itm.files])
        db_iiif_img = IIIFImage(iiif_info, id=image_ident)
        IIIFImage.save(db_iiif_img)
        for f in itm.files:
            db_img = Image(f.url, f.width, f.height, f.mimetype,
                           image_ident)
            Image.save(db_img)
        iiif_map[phys_id] = (image_ident, itm.label,
                             (largest_image.width, largest_image.height))
        thumbs_map[image_ident] = (smallest_image.width,
                                   smallest_image.height)
    return iiif_map, thumbs_map


def _notify_if_last(job_id, manifest_id):
    redis = get_redis()
    recipients = redis.smembers('recipients.{}'.format(job_id))
    for recipient in recipients:
        redis.srem('notifications.{}.jobs'.format(recipient), job_id)
        redis.sadd('notifications.{}.manifests'.format(recipient),
                   manifest_id)
        notify_email(recipient.decode('utf8'))
    redis.delete('recipients.{}'.format(job_id))


def import_mets_job(mets_url, collection_id=None, concurrency=2):
    job = get_current_job()
    try:
        xml = requests.get(mets_url, allow_redirects=True).content
        tree = ET.fromstring(xml)
        doc = mets.MetsDocument(tree, url=mets_url)
        if current_app.config['DUMP_METS']:
            xml_path = os.path.join(current_app.config['DUMP_METS'],
                                    doc.primary_id.replace('/', '_') + ".xml")
            with open(xml_path, "wb") as fp:
                fp.write(ET.tostring(tree, pretty_print=True))

        try:
            _read_files(doc, job, concurrency)
        except Exception as e:
            # Write images that could be read to database, as to a void
            # a costly re-scrape when the bug(?) gets fixed
            db_images = [Image(f.url, f.width, f.height, f.mimetype)
                         for f in doc.files.values()]
            Image.save(*db_images)
            db.session.commit()
            raise e
        if not doc.files:
            raise mets.MetsImportError(
                "METS at {} does not reference any JPEG images"
                .format(mets_url))
        doc.read_physical_items()
        doc.read_toc_entries()
        doc.read_metadata()

        existing_manifest = Manifest.by_origin(mets_url)
        if existing_manifest:
            manifest_id = existing_manifest.id
        else:
            manifest_id = doc.primary_id
        iiif_map, thumbs_map = _make_image_maps(doc)
        manifest = iiif.make_manifest(manifest_id, doc, iiif_map, thumbs_map)
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
        if job:
            _notify_if_last(job.id, manifest['@id'])
        return manifest['@id']
    except Exception as e:
        db.session.rollback()
        raise e


# NOTE: This is not actually a task, but since it depends on the tasks,
#       it lives in the same module...
def notify_email(recipient):
    redis = get_redis()
    jobs_key = 'notifications.{}.jobs'.format(recipient)
    num_outstanding_jobs = redis.scard(jobs_key)
    if num_outstanding_jobs > 0:
        return

    manifests_key = 'notifications.{}.manifests'.format(recipient)
    manifest_ids = redis.smembers(manifests_key)
    redis.delete(jobs_key, manifests_key)

    msg = EmailMessage()
    msg['Subject'] = 'Your IIIF manifests are ready'
    msg['From'] = 'notifications@{}'.format(current_app.config['SERVER_NAME'])
    msg['To'] = recipient
    msg.set_content(EMAIL_TEMPLATE.format("\n".join(
        url_for('view.view_endpoint', manifest_id=manifest_id, _external=True)
        for manifest_id in manifest_ids)))
    with smtplib.SMTP(current_app.config['SMTP_SERVER']) as s:
        s.login(current_app.config['SMTP_USER'],
                current_app.config['SMTP_PASSWORD'])
        s.send_message(msg, to_addrs=[recipient])


def import_from_oai(oai_endpoint, since=None):
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
