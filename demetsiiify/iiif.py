"""IIIF image and presentation logic."""
import logging
from itertools import chain
from typing import Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlencode

import shortuuid
from flask_sqlalchemy import Pagination
from iiif_prezi.factory import Manifest, ManifestFactory

from .mets import MetsDocument, TocEntry


#: Localized labels for metadata values
METAMAP = {
    'title': {'en': 'Title', 'de': 'Titel'},
    'language': {'en': 'Language', 'de': 'Sprache'},
    'genre': {'en': 'Genre', 'de': 'Genre'},
    'creator': {'en': 'Creator', 'de': 'Urheber'},
    'other_persons': {'en': 'Other Persons', 'de': 'Andere Personen'},
    'publisher': {'en': 'Publisher', 'de': 'Veröffentlicht von'},
    'pub_place': {'en': 'Publication Place', 'de': 'Publikationsort'},
    'pub_date': {'en': 'Publication Date', 'de': 'Erscheinungsdatum'}
}


#: Mapping from license shorthands to their full URIs
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


def make_label(mets_meta: dict) -> str:
    """Generate a descripte label for the given metadata set.

    Will take the form '{creator}: {label} ({pub_place}, {pub_date})'.

    :param mets_meta:   Metadata to generate label from
    :returns:           Generated label
    """
    label = mets_meta['title'][0]
    if mets_meta.get('creator'):
        label = "{creator}: {label}".format(
            creator="/".join(mets_meta['creator']),
            label=label)
    if mets_meta.get('pub_place') and mets_meta.get('pub_date'):
        label = "{label} ({pub_place}, {pub_date})".format(
            label=label, pub_place=mets_meta['pub_place'],
            pub_date=mets_meta['pub_date'])
    elif mets_meta.get('pub_date'):
        label = "{label} ({pub_date})".format(
            label=label, pub_date=mets_meta['pub_date'])
    elif mets_meta.get('pub_place'):
        label = "{label} ({pub_place})".format(
            label=label, pub_place=mets_meta['pub_place'])
    return label


def make_metadata(mets_meta: dict) -> List[dict]:
    """Generate metadata according to the IIIF Presentation API specification.

    :param mets_meta:   Metadata as extracted from the METS/MODS data
    :returns:           The IIIF metadata set
    """
    metadata = [{'label': METAMAP[k], 'value': v}
                for k, v in mets_meta.items()
                if k in METAMAP and v]
    metadata.extend({'label': label, 'value': value}
                    for label, value in mets_meta.items()
                    if 'Identifier' in label and value)
    return metadata


def _get_canvases(toc_entry: TocEntry, manifest: Manifest) -> List[str]:
    """Obtain list of canvas identifiers for a given TOC entry.

    :param toc_entry:       TOC entry to get canvases for
    :param manifest:        Manifest with canvases
    :returns:               All canvas ids for the given TOC entry
    """
    canvases = []
    for phys_id in toc_entry.physical_ids:
        canvas = next((c for c in manifest.sequences[0].canvases
                       if c.id.endswith(f'{phys_id}.json')), None)
        if canvas is None:
            logger.warning(f'Could not find a matching canvas for {phys_id}')
            continue
        canvases.append(canvas)
    if toc_entry.children:
        canvases.extend(chain.from_iterable(
            _get_canvases(child, manifest)
            for child in toc_entry.children))
    return canvases


def _add_toc_ranges(manifest: Manifest, toc_entries: Iterable[TocEntry]):
    """Add IIIF ranges to manifest for all given TOC entries.

    :param manifest:        The IIIF manifest to add the ranges to
    :param toc_entries:     TOC entries to add ranges for
    """
    for entry in toc_entries:
        if not entry.label or not entry.physical_ids:
            continue
        range = manifest.range(ident=entry.logical_id, label=entry.label)
        for canvas in _get_canvases(entry, manifest):
            range.add_canvas(canvas)
        for child in entry.children:
            range.range(ident=child.logical_id, label=child.label)
        _add_toc_ranges(manifest, entry.children)


def _make_empty_manifest(ident: str, label: str, base_url: str) -> Manifest:
    """Generate an empty IIIF manifest.

    :param ident:       Identifier for the manifest, that is not a URL, but
                        the `<ident>` in `https://..../<ident>/manifest`
    :param label:       Label for the manifest
    :param base_url:    Root URL for the application, e.g. https://example.com
    :returns:           The empty manifest
    """
    manifest_factory = ManifestFactory()
    manifest_ident = f'{base_url}/iiif/{ident}/manifest'
    manifest_factory.set_base_prezi_uri(f'{base_url}/iiif/{ident}')
    manifest_factory.set_base_image_uri(f'{base_url}/iiif/image')
    manifest_factory.set_iiif_image_info('2.0', 0)
    manifest = manifest_factory.manifest(ident=manifest_ident, label=label)
    return manifest


def _fill_manifest_metadata(manifest: Manifest, mets_metadata: dict) -> None:
    """Fill in metadata for an IIIF manifest.

    :param manifest:        Manifest to add metadata to
    :param mets_metadata:   Metadata extracted from a METS/MODS document
    """
    for meta in make_metadata(mets_metadata):
        manifest.set_metadata(meta)
    manifest.description = mets_metadata.get('description', '')
    manifest.seeAlso = mets_metadata.get('see_also', '')
    manifest.related = mets_metadata.get('related', '')
    manifest.attribution = mets_metadata.get('attribution', '')
    manifest.logo = mets_metadata.get('logo', '')
    manifest.license = LICENSE_MAP.get(mets_metadata.get('license', ''), '')


def make_image_infos(doc: MetsDocument,
                     base_url: str) -> Mapping[str, dict]:
    """Create info.json data structures for all physical items."""
    mapping = {}
    for phys_id, itm in doc.physical_items.items():
        sizes = [(f.width, f.height) for f in itm.files]
        max_width, max_height = max(sizes)
        mapping[phys_id] = {
            '@context': 'http://iiif.io/api/image/2/context.json',
            '@id': 'f{base_url}/iiif/image/{itm.image_ident}',
            'protocol': 'http://iiif.io/api/image',
            'profile': ['http://iiif.io/api/image/2/level0.json'],
            'width': max_width,
            'height': max_height,
            'sizes': [{'width': w, 'height': h} for w, h in sizes]}
    return mapping


def make_manifest(ident: str, mets_doc: MetsDocument,
                  base_url: str) -> dict:
    """Generate a IIIF manifest from the data extracted from METS document.

    :param ident:           Identifier of the document
    :param mets_doc:        METS document to generate manifest from
    :param base_url:        Root URL for the application,
    :returns:               Generated IIIF manifest
    """
    manifest = _make_empty_manifest(ident=ident, base_url=base_url,
                                    label=make_label(mets_doc.metadata))
    _fill_manifest_metadata(manifest, mets_doc.metadata)

    seq = manifest.sequence(ident='default')
    for page_id, page in mets_doc.physical_items.items():
        canvas = seq.canvas(ident=page_id, label=page.label or '?')
        anno = canvas.annotation(ident=page_id)
        img = anno.image(page.image_ident, iiif=True)
        canvas.width, canvas.height = page.max_dimensions
        img.set_hw(canvas.height, canvas.width)
        thumb_w, thumb_h = page.min_dimensions
        canvas.thumbnail = manifest._factory.image(
            page.image_ident, iiif=True, size=f'{thumb_w},{thumb_h}')
        canvas.thumbnail.set_hw(thumb_w, thumb_h)
    _add_toc_ranges(manifest, mets_doc.toc_entries)
    return manifest.toJSON(top=True)


def make_manifest_collection(
        pagination: Pagination, label: str, collection_id: str,
        per_page: int, base_url: str, page_num: Optional[int] = None,
        coll_counts: Optional[Tuple[int, str, int]] = None) -> dict:
    """Generate a IIIF collection.

    :param pagination:      Pagination query for all manifests of the
                            collection
    :param label:           Label for the collection
    :param collection_id:   Identifier of the collection
    :param base_url:        Root URL for the application,
                            e.g. https://example.com
    :param page_num:        Number of the collection page to display
    :returns:               The generated IIIF collection
    """
    collection_url = f'{base_url}/iiif/collection/{collection_id}'
    if page_num is not None:
        page_id = 'p{}'.format(page_num)
    else:
        page_id = 'top'
    collection = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": f'{base_url}/iiif/collection/{collection_id}/{page_id}',
        "@type": "sc:Collection",
        "total": pagination.total,
        "label": label,
    }
    if page_id == 'top':
        collection.update({
            "first": f'{collection_url}/p1',
            "last": f'{collection_url}/p{pagination.pages}'
        })
    else:
        if collection_id != 'index':
            collection['within'] = f'{collection_url}/top'
        collection.update({
            'startIndex': (pagination.page - 1) * pagination.per_page,
            'manifests': [{
                '@id': f'{base_url}/iiif/{m.id}/manifest',
                '@type': 'sc:Manifest',
                'label': m.label,
                'attribution': m.manifest['attribution'],
                'logo': m.manifest['logo'],
                'thumbnail': m.manifest.get(
                    'thumbnail',
                    m.manifest['sequences'][0]['canvases'][0]['thumbnail'])
            } for m in pagination.items]
        })
        if page_num == 1:
            collection['collections'] = []
            for cid, label, num_manifs in coll_counts:
                if not num_manifs:
                    continue
                # We create a mock pagination object that does not have
                # an underlying query, since we're only going to need
                # the manifest count when generating the top-level collection
                manifests_pagination = Pagination(
                    None, 1, per_page, num_manifs, None)
                iiif_coll = make_manifest_collection(
                    manifests_pagination, label, cid, None)
                collection['collections'].append(iiif_coll)
        if 'collections' in collection and not collection['collections']:
            del collection['collections']
        if pagination.has_next:
            collection['next'] = f'{collection_url}/p{pagination.next_num}'
        if pagination.has_prev:
            collection['prev'] = f'{collection_url}/p{pagination.prev_num}'
    return collection


def make_annotation_list(pagination: Pagination, request_url: str,
                         request_args: dict, base_url: str) -> dict:
    """Create a IIIF annotation list.

    :param pagination:      Pagination of annotations
    :param request_url:     Request URL for the annotation list, will be its
                            IIIF identifier
    :param request_args:    Request arguments for the annotation list request
    :param base_url:    Root URL for the application, e.g. https://example.com
    :returns:               The IIIF annotation list
    """
    def _make_link(page_no: int) -> str:
        params = urlencode({'p': page_no, **request_args})
        return f'{base_url}/iiif/annotation?{params}'

    params_first = urlencode({k: v for k, v in request_args.items()
                           if k != 'p'})
    out = {
        '@context': 'http://iiif.io/api/presentation/2/context.json',
        '@id': request_url,
        '@type': 'sc:AnnotationList',
        'within': {
            '@type': 'sc:Layer',
            'total': pagination.total,
            'first': _make_link(1),
            'last': _make_link(pagination.pages),
            'ignored': [k for k in request_args
                        if k not in ('q', 'motivation', 'date', 'user', 'p')]
        },
        'startIndex': (pagination.page - 1) * pagination.per_page,
        'resources': [a.annotation for a in pagination.items],
    }
    if pagination.has_next:
        out['next'] = _make_link(pagination.next_num)
    if pagination.has_prev:
        out['next'] = _make_link(pagination.prev_num)
    return out
