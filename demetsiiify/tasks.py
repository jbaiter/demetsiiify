import time
from collections import deque, OrderedDict

import lxml.etree as ET
import requests
import shortuuid
from rq import get_current_job

from . import mets
from . import iiif
from .models import db, Manifest, IIIFImage, Image


def import_mets_job(mets_url):
    job = get_current_job()
    try:
        xml = requests.get(mets_url, allow_redirects=True).content
        tree = ET.fromstring(xml)
        file_infos = {}
        times = deque(maxlen=50)
        start_time = time.time()
        for img_info, idx, total in mets.get_file_infos(tree, jpeg_only=True):
            duration = time.time() - start_time
            times.append(duration)
            file_infos[img_info.id] = img_info
            job.meta = dict(
                current_image=idx,
                total_images=total,
                eta=(sum(times)/len(times)) * (total - idx))
            job.save()
            start_time = time.time()
        phys_map = mets.physical_map(tree, file_infos)
        iiif_map = OrderedDict()
        thumbs_map = {}
        for phys_id, (label, files) in phys_map.items():
            image_ident = shortuuid.uuid()
            largest_image = max(files, key=lambda f: f.height)
            smallest_image = min(files, key=lambda f: f.height)
            iiif_info = iiif.make_info_data(
                image_ident, [(f.width, f.height) for f in files])
            db_iiif_img = IIIFImage(iiif_info, uuid=image_ident)
            IIIFImage.save(db_iiif_img)
            for f in files:
                db_img = Image(f.url, f.width, f.height, f.mimetype,
                               image_ident)
                Image.save(db_img)
            iiif_map[phys_id] = (image_ident, label,
                                 (largest_image.width, largest_image.height))
            thumbs_map[image_ident] = (smallest_image.width,
                                       smallest_image.height)
        metadata = mets.get_metadata(tree)
        toc_entries = mets.toc_entries(tree)
        existing_manifest = Manifest.by_metsurl(mets_url)
        if existing_manifest:
            manifest_id = existing_manifest.uuid
        else:
            manifest_id = shortuuid.uuid()
        manifest = iiif.make_manifest(manifest_id, tree, metadata, iiif_map,
                                      toc_entries, thumbs_map)
        db_manifest = Manifest(mets_url, manifest, uuid=manifest_id,
                               label=manifest['label'])
        Manifest.save(db_manifest)
        # Since the METS might have already been indexed, there's the
        # possibility that the IIIF images might have changed, leading to
        # orphaned images.
        IIIFImage.delete_orphaned()
        db.session.commit()
        return manifest['@id']
    except Exception as e:
        db.session.rollback()
        raise e
