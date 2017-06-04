import logging
from itertools import chain

import sqlalchemy.sql as sql
from flask import current_app, url_for
from flask_sqlalchemy import Pagination
from iiif_prezi.factory import ManifestFactory
from sqlalchemy.dialects import postgresql as pg

from .extensions import db


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


def make_label(mets_meta):
    """ Generate a descripte label for the given metadata set.

    Will take the form '{creator}: {label} ({pub_place}, {pub_date})'.

    :param mets_meta:   Metadata to generate label from
    :type mets_meta:    dict
    :returns:           Generated label
    :rtype:             str
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


def make_info_data(identifier, sizes):
    """ Generate IIIF Image API info.json data for an image.

    :param identifier:  Identifier of the image
    :type identifier:   str
    :param sizes:       Available image sizes (width, height)
    :type sizes:        iterable of (int, int)
    :returns:           info.json data
    :rtype:             dict
    """
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
    """ Generate metadata according to the IIIF Presentation API specification.

    :param mets_meta:   Metadata as extracted from the METS/MODS data
    :type mets_meta:    dict
    :returns:           The IIIF metadata set
    :rtype:             dict
    """
    metadata = [{'label': METAMAP[k],
                 'value': v} for k, v in mets_meta.items() if k in METAMAP]
    metadata.extend({'label': label, 'value': value}
                    for label, value in mets_meta.items()
                    if 'Identifier' in label)
    return metadata


def _get_canvases(toc_entry, phys_to_canvas):
    """ Obtain list of canvas identifiers for a given TOC entry.

    :param toc_entry:       TOC entry to get canvases for
    :type toc_entry:        :py:class:`demetsiiify.mets.MetsTocEntry`
    :param phys_to_canvas:  Mapping from METS physical ids to canvas ids
    :type phys_to_canvas:   dict
    :returns:               All canvas ids for the given TOC entry
    :rtype:                 list of str
    """
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
    """ Add IIIF ranges to manifest for all given TOC entries.

    :param manifest:        The IIIF manifest to add the ranges to
    :type manifest:         :py:class:`iiif_prezi.factory.Manifest`
    :param toc_entries:     TOC entries to add ranges for
    :type toc_entries:      list of :py:class:`demetsiiify.mets.MetsTocEntry`
    :param phys_to_canvas:  Mapping from METS physical ids to IIIF canvas ids
    :type phys_to_canvas:   dict
    :param idx:             Numerical index of the previous range
    :type idx:              int
    :returns:               Numerical index of the last range added
    :rtype:                 int
    """
    for entry in toc_entries:
        if entry.label:
            range = manifest.range(ident='r{}'.format(idx), label=entry.label)
            for canvas in _get_canvases(entry, phys_to_canvas):
                range.add_canvas(canvas)
            idx += 1
        idx = _add_toc_ranges(manifest, entry.children, phys_to_canvas, idx)
    return idx


def _make_empty_manifest(ident, label):
    """ Generate an empty IIIF manifest.

    :param ident:       Identifier for the manifest
    :type ident:        str
    :param label:       Label for the manifest
    :type label:        str
    :returns:           The empty manifest
    :rtype:             :py:class:`iiif_prezi.factory.Manifest`
    """
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
                                         label=make_label(mets_doc.metadata))
    return manifest


def _fill_manifest_metadata(manifest, mets_metadata):
    """ Fill in metadata for an IIIF manifest.

    :param manifest:        Manifest to add metadata to
    :type manifest:         :py:class:`iiif_prezi.factory.Manifest`
    :param mets_metadata:   Metadata extracted from a METS/MODS document
    :type mets_metadata:    dict
    """
    for meta in make_metadata(mets_metadata):
        manifest.set_metadata(meta)
    manifest.description = mets_metadata.get('description') or ''
    manifest.seeAlso = mets_metadata.get('see_also') or ''
    manifest.related = mets_metadata.get('related') or ''
    manifest.attribution = mets_metadata.get('attribution') or ''
    manifest.logo = mets_metadata.get('logo', '')
    manifest.license = LICENSE_MAP.get(mets_metadata.get('license'), '')


def make_manifest(ident, mets_doc, physical_map, thumbs_map):
    """ Generate a IIIF manifest from the data extracted from METS document.

    :param ident:           Identifier of the document
    :type ident:            str
    :param mets_doc:        METS document to generate manifest from
    :type mets_doc:         :py:class:`demetsiiify.mets.MetsDocument`
    :param physical_map:    Mapping from physical id to
                            (image_id, label, (w, h))
    :type physical_map:     {str: (str, str, (int, int))} dict
    :param thumbs_map:      Mapping from image id to (thumb_w, thumb_h)
    :type thumbs_map:       {str: (int, int)} dict
    :returns:               Generated IIIF manifest
    :rtype:                 dict
    """
    manifest = _make_empty_manifest(ident=manifest_ident,
                                    label=make_label(mets_doc.metadata))
    _fill_manifest_metadata(manifest)

    phys_to_canvas = {}
    seq = manifest.sequence(ident='default')
    for idx, (phys_id, (image_id, label, (width, height))) in enumerate(
            physical_map.items(), start=1):
        page_id = 'p{}'.format(idx)
        canvas = seq.canvas(ident=page_id, label=label or '?')
        anno = canvas.annotation(ident=page_id)
        img = anno.image(image_id, iiif=True)
        img.set_hw(height, width)
        canvas.width = img.width
        canvas.height = img.height
        thumb_width, thumb_height = thumbs_map[image_id]
        canvas.thumbnail = url_for(
            'iiif.get_image', image_id=image_id, region='full',
            size="{},{}".format(thumb_width, thumb_height),
            rotation='0', quality='default', format='jpg',
            _external=True, _scheme=current_app.config['PREFERRED_URL_SCHEME'])
        phys_to_canvas[phys_id] = canvas.id
    _add_toc_ranges(manifest, mets_doc.toc_entries, phys_to_canvas)
    return manifest.toJSON(top=True)


def make_manifest_collection(pagination, label, collection_id, page_num=None):
    """ Generate a IIIF collection.

    :param pagination:      Pagination query for all manifests of the
                            collection
    :type pagination:       :py:class:`flask_sqlalchemy.Pagination`
    :param label:           Label for the collection
    :type label:            str
    :param collection_id:   Identifier of the collection
    :type collection_id:    str
    :param page_num:        Number of the collection page to display
    :type page_num:         int
    :returns:               The generated IIIF collection
    :rtype:                 dict
    """
    if page_num is not None:
        page_id = 'p{}'.format(page_num)
    else:
        page_id = 'top'
    collection = {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": url_for('iiif.get_collection', collection_id=collection_id,
                       page_id=page_id, _external=True),
        "@type": "sc:Collection",
        "total": pagination.total,
        "label": label,
    }
    if collection_id != 'index':
        collection['within'] = url_for(
            'iiif.get_collection', collection_id='index', page_id='top',
            _external=True)
    if page_id == 'top':
        collection.update({
            "first": url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p1', _external=True),
            "last": url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.pages), _external=True)
        })
    else:
        collection.update({
            'within': url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='top', _external=True),
            'startIndex': (pagination.page-1) * pagination.per_page,
            'manifests': [{
                '@id': url_for('iiif.get_manifest', manif_id=m.id,
                               _external=True),
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
            # NOTE: This might be a bit unwieldy, but previously we
            # used a for-loop and had to run `num_collections` separate
            # queries, which was horrible performance-wise
            if collection_id == 'index':
                parent_query = 'IS NULL'
                params = {}
            else:
                parent_query = '= :parent_id'
                params = dict(parent_id=parent_id)
            coll_counts = db.session.execute(sql.text(
                    'SELECT c.id, c.label, '
                    '       count(cm.manifest_id) as num_manifests '
                    '  FROM collection_manifest AS cm '
                    '  JOIN collection AS c '
                    '    ON c.surrogate_id = cm.collection_id '
                    '       AND c.parent_collection_id {} '
                    '  GROUP BY c.id, c.label '
                    '  ORDER BY c.id'.format(parent_query)), params).fetchall()
            for cid, label, num_manifs in coll_counts:
                if not num_manifs:
                    continue
                # We create a mock pagination object that does not have
                # an underlying query, since we're only going to need
                # the manifest count when generating the top-level collection
                manifests_pagination = Pagination(
                    None, 1, current_app.config['ITEMS_PER_PAGE'],
                    num_manifs, None)
                iiif_coll = make_manifest_collection(
                    manifests_pagination, label, cid, None)
                collection['collections'].append(iiif_coll)
        if not collection['collections']:
            del collection['collections']
        if pagination.has_next:
            collection['next'] = url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.next_num), _external=True)
        if pagination.has_prev:
            collection['prev'] = url_for(
                'iiif.get_collection', collection_id=collection_id,
                page_id='p{}'.format(pagination.prev_num), _external=True)
    return collection


def make_annotation_list(pagination, request_url, request_args):
    """ Create a IIIF annotation list.

    :param pagination:      Pagination of annotations
    :type pagination:       :py:class:`flask_sqlalchemy.Pagination`
    :param request_url:     Request URL for the annotation list, will be its
                            IIIF identifier
    :type request_url:      str
    :param request_args:    Request arguments for the annotation list request
    :type request_args:     dict
    :returns:               The IIIF annotation list
    :rtype:                 dict
    """
    out = {
        '@context': 'http://iiif.io/api/presentation/2/context.json',
        '@id': request_url,
        '@type': 'sc:AnnotationList',
        'within': {
            '@type': 'sc:Layer',
            'total': pagination.total,
            'first': url_for('iiif.search_annotations', p=1, _external=True,
                             **{k: v for k, v in request_args.items()
                                if k != 'p'}),
            'last': url_for('iiif.search_annotations', p=pagination.pages,
                            _external=True,
                            **{k: v for k, v in request_args.items()
                               if k != 'p'}),
            'ignored': [k for k in request_args
                        if k not in ('q', 'motivation', 'date', 'user', 'p')]
        },
        'startIndex': (pagination.page-1) * pagination.per_page,
        'resources': [a.annotation for a in pagination.items],
    }
    if pagination.has_next:
        out['next'] = url_for(
            'iiif.search_annotations', p=pagination.next_num,
            _external=True,
            **{k: v for k, v in request_args.items()
                if k != 'p'})
    if pagination.has_prev:
        out['next'] = url_for(
            'iiif.search_annotations', p=pagination.prev_num,
            _external=True,
            **{k: v for k, v in request_args.items()
                if k != 'p'})
    return out
