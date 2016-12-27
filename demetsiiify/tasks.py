import time
from collections import deque, OrderedDict

import lxml.etree as ET
import requests
import shortuuid
from rq import get_current_job

from . import mets
from . import iiif
from .models import db, Manifest, IIIFImage, Image, Identifier


def import_mets_job(mets_url):
    job = get_current_job()
    try:
        xml = requests.get(mets_url, allow_redirects=True).content
        tree = ET.fromstring(xml)
        doc = mets.MetsDocument(tree, url=mets_url)

        times = deque(maxlen=50)
        start_time = time.time()
        for idx, total in doc.read_files(jpeg_only=True, yield_progress=True):
            duration = time.time() - start_time
            times.append(duration)
            if job:
                job.meta = dict(
                    current_image=idx,
                    total_images=total,
                    eta=(sum(times)/len(times)) * (total - idx))
                job.save()
            start_time = time.time()
        if not doc.files:
            raise mets.MetsImportError(
                "METS at {} does not reference any JPEG images"
                .format(mets_url))
        doc.read_physical_items()
        doc.read_toc_entries()
        doc.read_metadata()

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

        existing_manifest = Manifest.by_origin(mets_url)
        if existing_manifest:
            manifest_id = existing_manifest.id
        else:
            manifest_id = doc.primary_id
        manifest = iiif.make_manifest(manifest_id, doc, iiif_map, thumbs_map)
        db_manifest = Manifest(mets_url, manifest, id=manifest_id,
                               label=manifest['label'])
        db_manifest.identifiers = [
            Identifier(id_, type, db_manifest.id)
            for type, id_ in doc.identifiers.items()]
        Manifest.save(db_manifest)
        Identifier.save(*db_manifest.identifiers)

        # Since the METS might have already been indexed, there's the
        # possibility that the IIIF images might have changed, leading to
        # orphaned images.
        IIIFImage.delete_orphaned()
        db.session.commit()
        return manifest['@id']
    except Exception as e:
        db.session.rollback()
        raise e
