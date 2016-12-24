import functools
from collections import OrderedDict, namedtuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from wand.image import Image

from . import models

NAMESPACES = {
    'mets': 'http://www.loc.gov/METS/',
    'mods': 'http://www.loc.gov/mods/v3',
    'dv': 'http://dfg-viewer.de/',
    'xlink': 'http://www.w3.org/1999/xlink'}

# For some reason, some libraries use the wrong MIME type...
JPEG_MIMES = ('image/jpeg', 'image/jpg')


ImageInfo = namedtuple('ImageInfo',
                       ('id', 'url', 'mimetype', 'width', 'height'))
MetsTocEntry = namedtuple('MetsTocEntry', ('children', 'phys_ids', 'log_id',
                                           'label', 'type'))


def _make_helpers(elem):
    xpath = functools.partial(elem.xpath, namespaces=NAMESPACES)
    findall = functools.partial(elem.findall, namespaces=NAMESPACES)
    findtext = functools.partial(elem.findtext, namespaces=NAMESPACES)
    return xpath, findall, findtext


def parse_title(title_elem):
    xpath, findall, findtext = _make_helpers(title_elem)
    title = findtext(".//mods:title")
    nonsort = findtext(".//mods:nonSort")
    if nonsort:
        title = nonsort + title
    subtitle = findtext(".//mods:subTitle")
    if subtitle:
        title = "{title}. {subtitle}".format(title=title, subtitle=subtitle)
    return title


def parse_name(name_elem):
    xpath, findall, findtext = _make_helpers(name_elem)
    name = findtext("./mods:displayForm")
    if not name:
        name = " ".join(findtext("./mods:namePart"))
    return name


def get_metadata(mets_tree, mets_url=None):
    # Utility functions to reduce verbosity (I hate XML namespaces...)
    xpath, findall, findtext = _make_helpers(mets_tree)
    metadata = OrderedDict()

    metadata['creator'] = [
        parse_name(e)
        for e in xpath(".//mets:dmdSec[1]//"
                       "mods:name[./mods:role/mods:roleTerm/text() = 'aut']")]
    metadata['other_persons'] = [
        parse_name(e)
        for e in xpath(".//mets:dmdSec[1]//"
                       "mods:name[./mods:role/mods:roleTerm/text() != 'aut']")]

    titles = [parse_title(e)
              for e in findall(".//mets:dmdSec[1]//mods:mods/mods:titleInfo")]
    if not titles:
        # For items with no title of their own that are part of a larger
        # multi-volume work
        titles = [parse_title(
            findall(".//mods:relatedItem[@type='host']/mods:titleInfo")[0])]
    part_number = findtext(".//mods:part/mods:detail/mods:number")
    if part_number:
        titles = [
            "{title} ({part_no})".format(title=title, part_no=part_number)
            for title in titles]
    metadata['title'] = titles

    for id_elem in findall(".//mods:identifier"):
        metadata['Identifier ({})'.format(id_elem.get('type'))] = id_elem.text
    metadata['attribution'] = "<a href='{}'>{}</a>".format(
            findtext(".//mets:rightsMD//dv:ownerSiteURL"),
            findtext(".//mets:rightsMD//dv:owner"))
    metadata['logo'] = findtext(".//mets:rightsMD//dv:ownerLogo")
    metadata['see_also'] = []
    if mets_url:
        metadata['see_also'].append(
            [{'@id': mets_url, 'format': 'text/xml',
              'profile': 'http://www.loc.gov/METS/'}])
    pdf_url = xpath(".//mets:fileGrp[@USE='DOWNLOAD']/"
                    "mets:file[@MIMETYPE='application/pdf']/"
                    "mets:FLocat/@xlink:href")
    if pdf_url:
        metadata['see_also'].append(
            {'@id': pdf_url, 'format': 'application/pdf'})
    metadata['related'] = findtext(".//mets:digiprovMD//dv:presentation")
    metadata['license'] = findtext(".//dv:rights/dv:license") or 'reserved'

    # TODO: mods:originInfo
    # TODO: mods:physicalDescription
    metadata['language'] = findtext(".//mods:languageTerm[@type='text']")
    metadata['genre'] = findtext(".//mods:genre")
    metadata['description'] = findtext(".//mods:abstract")
    # TODO: Add mods:notes to description
    return OrderedDict((k, v) for k, v in metadata.items() if v)


def get_file_infos(mets_tree, jpeg_only=False):
    _, findall, _ = _make_helpers(mets_tree)
    mets_info = [(id_, location, mimetype, models.Image.by_url(location))
                 for id_, location, mimetype in
                 (get_image_location(e) for e in findall(".//mets:file"))
                 if location.startswith('http')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(image_info, id_, loc, mime, info)
                for id_, loc, mime, info in mets_info
                if not jpeg_only or mime in JPEG_MIMES]
        for idx, fut in enumerate(as_completed(futs), start=1):
            yield fut.result(), idx, len(futs)


def physical_map(mets_tree, file_infos):
    """ Create a map from physical IDs to (label, image_info) pairs from the
        METS' `structMap[@TYPE='PHYSICAL']`.
    """
    pages = mets_tree.findall(
        ".//mets:structMap[@TYPE='PHYSICAL']"
        "/mets:div[@TYPE='physSequence']"
        "/mets:div[@TYPE='page']", namespaces=NAMESPACES)
    pmap = OrderedDict()
    for page_elem in sorted(pages, key=lambda e: int(e.get('ORDER'))):
        page_id = page_elem.get('ID')
        for label_attr in ('LABEL', 'ORDERLABEL', 'ORDER'):
            label = page_elem.get(label_attr)
            if label is not None:
                break
        if label is None:
            label = '?'
        files = [
            file_infos.get(ptr.get('FILEID'))
            for ptr in page_elem.findall("./mets:fptr",
                                         namespaces=NAMESPACES)]
        pmap[page_id] = (label, [f for f in files if f is not None])
    return pmap


def parse_tocentry(root, lmap):
    """ Parse a toc entry subtree to a MetsTocEntry object """
    log_id = root.get('ID')
    entry = MetsTocEntry(
        children=[], phys_ids=lmap.get(log_id, []), type=root.get('TYPE'),
        log_id=log_id, label=root.get('LABEL'))
    for e in root.findall("./mets:div", namespaces=NAMESPACES):
        entry.children.append(parse_tocentry(e, lmap))
    return entry


def toc_entries(mets_tree):
    """ Create trees of TocEntries from the METS' `structMap[@TYPE='LOGICAL']`.
    """
    xpath, findall, findtext = _make_helpers(mets_tree)
    lmap = OrderedDict()
    mappings = [
        (e.get('{%s}from' % NAMESPACES['xlink']),
         e.get('{%s}to' % NAMESPACES['xlink']))
        for e in findall(".//mets:structLink//mets:smLink")]
    for lid, pid in mappings:
        if lid not in lmap:
            lmap[lid] = []
        lmap[lid].append(pid)

    toc_entries = [
        parse_tocentry(e, lmap)
        for e in xpath(".//mets:structMap[@TYPE='LOGICAL']/mets:div")]
    return toc_entries


def get_image_location(felem):
    image_id = felem.get('ID')
    mimetype = felem.get('MIMETYPE')
    # Seriously, I loathe XML namespaces...
    location = felem.find(
        "./mets:FLocat[@LOCTYPE='URL']",
        namespaces=NAMESPACES).get('{%s}href' % (NAMESPACES['xlink']))
    return image_id, location, mimetype


def image_info(id_, location, mimetype, known_info):
    """ Parse image information from a filePtr element. """
    if known_info is None:
        img = None
        attempts = 0
        while img is None:
            try:
                img = Image(
                    blob=requests.get(location, allow_redirects=True).content)
            except Exception as e:
                if attempts < 3:
                    attempts += 1
                else:
                    raise e
    else:
        img = known_info
    return ImageInfo(id_, location, mimetype, img.width, img.height)
