import logging
from itertools import chain

from flask import current_app, url_for
from iiif_prezi.factory import ManifestFactory


METAMAP = {
    'title': {'en': 'Title', 'de': 'Titel'},
    'language': {'en': 'Language', 'de': 'Sprache'},
    'genre': {'en': 'Genre', 'de': 'Genre'},
    'creator': {'en': 'Creator', 'de': 'Urheber'},
    'other_persons': {'en': 'Other Persons', 'de': 'Andere Personen'}
}


LICENSE_MAP = {
    'pdm': 'http://creativecommons.org/licenses/publicdomain/',
    'cc0': 'https://creativecommons.org/publicdomain/zero/1.0/',
    'cc-by': 'http://creativecommons.org/licenses/by/4.0',
    'cc-by-sa': 'http://creativecommons.org/licenses/by-sa/4.0',
    'cc-by-nd': 'http://creativecommons.org/licenses/by-nd/4.0',
    'cc-by-nc': 'http://creativecommons.org/licenses/by-nd/4.0',
    'cc-by-nc-sa': 'http://creativecommons.org/licenses/by-nc-sa/4.0',
    'cc-by-nc-nd': 'http://creativecommons.org/licenses/by-nc-nd/4.0'}


logger = logging.getLogger(__name__)


def make_info_data(identifier, sizes):
    max_width, max_height = max(sizes)
    return {
        '@context': 'http://iiif.io/api/image/2/context.json',
        '@id': '{}://{}/iiif/image/{}'.format(
            current_app.config['PREFERRED_URL_SCHEME'],
            current_app.config['SERVER_NAME'], identifier),
        'protocol': 'http://iiif.io/api/image',
        'profile': ['http://iiif.io/api/image/2/level0.json'],
        'width': max_width,
        'height': max_height,
        'sizes': [{'width': w, 'height': h} for w, h in sizes]}


def make_metadata(mets_meta):
    metadata = [{'label': METAMAP[k],
                 'value': v} for k, v in mets_meta.items() if k in METAMAP]
    metadata.extend({'label': label, 'value': value}
                    for label, value in mets_meta.items()
                    if 'Identifier' in label)
    return metadata


def _get_canvases(toc_entry, phys_to_canvas):
    canvases = []
    for phys_id in toc_entry.phys_ids:
        if phys_id not in phys_to_canvas:
            logger.warn('Could not find a matching canvas for {}'
                        .format(phys_id))
        else:
            canvases.append(phys_to_canvas[phys_id])
    if toc_entry.children:
        canvases.extend(chain.from_iterable(
            _get_canvases(child, phys_to_canvas)
            for child in toc_entry.children))
    return canvases


def _add_toc_ranges(manifest, toc_entries, phys_to_canvas, idx=0):
    for entry in toc_entries:
        if entry.label:
            range = manifest.range(ident='r{}'.format(idx), label=entry.label)
            for canvas in _get_canvases(entry, phys_to_canvas):
                range.add_canvas(canvas)
            idx += 1
        idx = _add_toc_ranges(manifest, entry.children, phys_to_canvas, idx)
    return idx


def make_manifest(ident, mets_tree, metadata, physical_map, toc_entries,
                  thumbs_map):
    manifest_factory = ManifestFactory()

    manifest_ident = '{}://{}/iiif/{}/manifest'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'], ident)
    manifest_factory.set_base_prezi_uri('{}://{}/iiif/{}'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'], ident))
    manifest_factory.set_base_image_uri('{}://{}/iiif/image'.format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME']))
    manifest_factory.set_iiif_image_info('2.0', 0)

    manifest = manifest_factory.manifest(ident=manifest_ident,
                                         label=metadata['title'][0])
    for meta in make_metadata(metadata):
        manifest.set_metadata(meta)
    manifest.description = metadata.get('description', '')
    manifest.seeAlso = metadata.get('see_also', '')
    manifest.related = metadata.get('related', '')
    manifest.attribution = metadata.get('attribution', '')
    manifest.logo = metadata.get('logo', '')
    manifest.license = LICENSE_MAP.get(metadata.get('license'), '')

    phys_to_canvas = {}
    seq = manifest.sequence(ident='default')
    for idx, (phys_id, (image_id, label, (width, height))) in enumerate(
            physical_map.items(), start=1):
        page_id = 'p{}'.format(idx)
        canvas = seq.canvas(ident=page_id, label=label)
        anno = canvas.annotation(ident=page_id)
        img = anno.image(image_id, iiif=True)
        img.set_hw(height, width)
        canvas.width = img.width
        canvas.height = img.height
        thumb_width, thumb_height = thumbs_map[image_id]
        canvas.thumbnail = url_for(
            'iiif.get_image', image_uuid=image_id, region='full',
            size="{},{}".format(thumb_width, thumb_height),
            rotation='0', quality='default', format='jpg',
            _external=True, _scheme=current_app.config['PREFERRED_URL_SCHEME'])
        phys_to_canvas[phys_id] = canvas.id
    _add_toc_ranges(manifest, toc_entries, phys_to_canvas)
    return manifest.toJSON(top=True)
