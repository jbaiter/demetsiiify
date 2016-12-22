import time
from collections import deque, OrderedDict

import lxml.etree as ET
import shortuuid
from flask import current_app

from . import make_celery
from . import mets
from . import iiif
from .models import db, Manifest, IIIFImage, Image


celery = make_celery(current_app)


@celery.task(bind=True, name='tasks.import_mets')
def import_mets_job(self, mets_url):
    tree = ET.parse(mets_url)
    file_infos = {}
    times = deque(maxlen=50)
    start_time = time.time()
    for img_info, idx, total in mets.get_file_infos(tree, jpeg_only=True):
        duration = time.time() - start_time
        times.append(duration)
        file_infos[img_info.id] = img_info
        self.update_state(
            state='PROGRESS',
            meta={'current_image': idx, 'total_images': total,
                  'eta': (sum(times)/len(times)) * (total - idx)})
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
            db_img = Image(f.url, f.width, f.height, f.mimetype, image_ident)
            Image.save(db_img)
        iiif_map[phys_id] = (image_ident, label,
                             (largest_image.width, largest_image.height))
        thumbs_map[image_ident] = (smallest_image.width, smallest_image.height)
    metadata = mets.get_metadata(tree)
    toc_entries = mets.toc_entries(tree)
    manifest_id = shortuuid.uuid()
    manifest = iiif.make_manifest(manifest_id, tree, metadata, iiif_map,
                                  toc_entries, thumbs_map)
    db_manifest = Manifest(mets_url, manifest, uuid=manifest_id,
                           label=manifest['label'])
    Manifest.save(db_manifest)
    # Since the METS might have already been indexed, there's the possibility
    # that the IIIF images might have changed, leading to orphaned images.
    IIIFImage.delete_orphaned()
    db.session.commit()
    return manifest['@id']
