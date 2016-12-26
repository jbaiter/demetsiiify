import io
from collections import OrderedDict, namedtuple, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

import lxml.etree as etree
import requests
from PIL import Image
from requests.packages.urllib3 import Retry

from . import models

NAMESPACES = {
    'mets': 'http://www.loc.gov/METS/',
    'mods': 'http://www.loc.gov/mods/v3',
    'dv': 'http://dfg-viewer.de/',
    'xlink': 'http://www.w3.org/1999/xlink'}

# For some reason, some libraries use the wrong MIME type...
JPEG_MIMES = ('image/jpeg', 'image/jpg')


# Utility datatypes
PhysicalItem = namedtuple('PhysicalItem', ('label', 'files'))
ImageInfo = namedtuple('ImageInfo',
                       ('id', 'url', 'mimetype', 'width', 'height'))
MetsTocEntry = namedtuple('MetsTocEntry', ('children', 'phys_ids', 'log_id',
                                           'label', 'type'))


class MetsImportError(Exception):
    def __init__(self, message, debug_info=None):
        super().__init__(message)
        self.debug_info = debug_info


# NOTE: This is not a generic METS parser, but currently highly coupled to both
# the METS/MODS profile required by the German 'DFG Viewer' and the later use
# as IIIF metadata (which is **not** intended to be machine-readable)
class MetsDocument:
    @classmethod
    def from_url(cls, metsurl):
        return cls(etree.parse(metsurl), metsurl)

    def __init__(self, mets_tree, url=None):
        self.url = url
        self._tree = mets_tree
        self.files = None
        self.physical_items = None
        self.toc_entries = None
        self.metadata = OrderedDict()

    def _xpath(self, xpath, elem=None):
        elem = elem if elem is not None else self._tree
        return elem.xpath(xpath, namespaces=NAMESPACES)

    def _find(self, path, elem=None):
        elem = elem if elem is not None else self._tree
        return elem.find(path, namespaces=NAMESPACES)

    def _findall(self, path, elem=None):
        elem = elem if elem is not None else self._tree
        return elem.findall(path, namespaces=NAMESPACES)

    def _findtext(self, path, elem=None):
        elem = elem if elem is not None else self._tree
        return elem.findtext(path, namespaces=NAMESPACES)

    def _parse_title(self, title_elem):
        title = self._findtext(".//mods:title", title_elem)
        nonsort = self._findtext(".//mods:nonSort", title_elem)
        if nonsort:
            title = nonsort + title
        subtitle = self._findtext(".//mods:subTitle", title_elem)
        if subtitle:
            title = "{title}. {subtitle}".format(title=title,
                                                 subtitle=subtitle)
        return title

    def _parse_name(self, name_elem):
        name = self._findtext("./mods:displayForm", name_elem)
        if not name:
            name = " ".join(self._findtext("./mods:namePart", name_elem))
        return name

    def _read_persons(self):
        persons = defaultdict(list)
        name_elems = self._xpath(
            ".//mets:dmdSec[1]//mods:name[./mods:role/mods:roleTerm]")
        for e in name_elems:
            name = self._parse_name(e)
            role = self._findtext("./mods:role/mods:roleTerm", e)
            if role == 'aut':
                persons['creator'].append(name)
            else:
                persons['other_persons'].append(name)
        return persons

    def _read_titles(self):
        title_elems = self._findall(
            ".//mets:dmdSec[1]//mods:mods/mods:titleInfo")
        if not title_elems:
            # For items with no title of their own that are part of a larger
            # multi-volume work
            title_elems = [self._findall(
                ".//mods:relatedItem[@type='host']/mods:titleInfo")[0]]
        titles = [self._parse_title(e) for e in title_elems]
        part_number = self._findtext(".//mods:part/mods:detail/mods:number")
        if part_number:
            titles = [
                "{title} ({part_no})".format(title=title, part_no=part_number)
                for title in titles]
        return titles

    def read_metadata(self, mets_url=None):
        self.metadata.update(self._read_persons())
        self.metadata['title'] = self._read_titles()

        self.metadata['identifiers'] = {}
        for id_elem in self._findall(".//mods:identifier"):
            self.metadata['identifiers'][id_elem.get('type')] = id_elem.text

        self.metadata['attribution'] = "<a href='{}'>{}</a>".format(
            self._findtext(".//mets:rightsMD//dv:ownerSiteURL"),
            self._findtext(".//mets:rightsMD//dv:owner"))
        self.metadata['logo'] = self._findtext(
            ".//mets:rightsMD//dv:ownerLogo")

        self.metadata['see_also'] = []
        if self.url:
            self.metadata['see_also'].append(
                [{'@id': mets_url, 'format': 'text/xml',
                  'profile': 'http://www.loc.gov/METS/'}])
        pdf_url = self._xpath(
            ".//mets:fileGrp[@USE='DOWNLOAD']/"
            "mets:file[@MIMETYPE='application/pdf']/"
            "mets:FLocat/@xlink:href")
        if pdf_url:
            self.metadata['see_also'].append(
                {'@id': pdf_url, 'format': 'application/pdf'})
        self.metadata['related'] = self._findtext(
            ".//mets:digiprovMD//dv:presentation")
        self.metadata['license'] = self._findtext(
            ".//dv:rights/dv:license") or 'reserved'

        # TODO: mods:originInfo
        # TODO: mods:physicalDescription
        self.metadata['language'] = self._findtext(
            ".//mods:languageTerm[@type='text']")
        self.metadata['genre'] = self._findtext(".//mods:genre")
        self.metadata['description'] = self._findtext(".//mods:abstract") or ""
        # TODO: Add mods:notes to description

    def read_files(self, jpeg_only=False, yield_progress=True):
        self.files = OrderedDict()
        mets_info = [
            (id_, location, mimetype)
            for id_, location, mimetype in
            (self._get_image_specs(e) for e in self._findall(".//mets:file"))
            if location.startswith('http')]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = []
            for id_, loc, mime, in mets_info:
                db_info = models.Image.by_url(loc)
                if db_info is None:
                    futs.append(pool.submit(image_info, id_, loc, mime,
                                            jpeg_only=True))
                else:
                    fut = Future()
                    fut.set_result(ImageInfo(id_, loc, mime, db_info.width,
                                             db_info.height))
                    futs.append(fut)
            for idx, fut in enumerate(as_completed(futs), start=1):
                if isinstance(fut, ImageInfo):
                    info = fut
                else:
                    try:
                        info = fut.result()
                    except Exception as e:
                        # Cancel pending futures, or else we'd have to wait
                        # for them to finish
                        for fut in futs:
                            if not fut.running() and not fut.done():
                                fut.cancel()
                        raise MetsImportError(
                            "Could not get image dimensions.") from e
                if info is not None:
                    self.files[info.id] = info
                    if yield_progress:
                        yield idx, len(futs)

    def read_physical_items(self):
        """ Create a map from physical IDs to (label, image_info) pairs from
            the METS' `structMap[@TYPE='PHYSICAL']`.
        """
        self.physical_items = OrderedDict()
        pages = self._findall(
            ".//mets:structMap[@TYPE='PHYSICAL']"
            "/mets:div[@TYPE='physSequence']"
            "/mets:div[@TYPE='page']")
        for page_elem in sorted(pages, key=lambda e: int(e.get('ORDER'))):
            page_id = page_elem.get('ID')
            for label_attr in ('LABEL', 'ORDERLABEL', 'ORDER'):
                label = page_elem.get(label_attr)
                if label is not None:
                    break
            if label is None:
                label = '?'
            files = [
                self.files[ptr.get('FILEID')]
                for ptr in self._findall("./mets:fptr", page_elem)
                if ptr.get('FILEID') in self.files]
            self.physical_items[page_id] = PhysicalItem(
                label, [f for f in files if f is not None])

    def _parse_tocentry(self, toc_elem, lmap):
        """ Parse a toc entry subtree to a MetsTocEntry object """
        log_id = toc_elem.get('ID')
        entry = MetsTocEntry(
            children=[], phys_ids=lmap.get(log_id, []),
            type=toc_elem.get('TYPE'),
            log_id=log_id, label=toc_elem.get('LABEL'))
        for e in self._findall("./mets:div", toc_elem):
            entry.children.append(self._parse_tocentry(e, lmap))
        return entry

    def read_toc_entries(self):
        """ Create trees of TocEntries from the METS' `structMap[@TYPE='LOGICAL']`.
        """
        self.toc_entries = []
        lmap = OrderedDict()
        mappings = [
            (e.get('{%s}from' % NAMESPACES['xlink']),
             e.get('{%s}to' % NAMESPACES['xlink']))
            for e in self._findall(".//mets:structLink//mets:smLink")]
        for lid, pid in mappings:
            if lid not in lmap:
                lmap[lid] = []
            lmap[lid].append(pid)
        for e in self._xpath(".//mets:structMap[@TYPE='LOGICAL']/mets:div"):
            self.toc_entries.append(self._parse_tocentry(e, lmap))

    def _get_image_specs(self, felem):
        image_id = felem.get('ID')
        mimetype = felem.get('MIMETYPE')
        # Seriously, I loathe XML namespaces...
        location = (
            self._find("./mets:FLocat[@LOCTYPE='URL']", felem)
                .get('{%s}href' % (NAMESPACES['xlink'])))
        return image_id, location, mimetype


def image_info(id_, location, mimetype, jpeg_only=False):
    """ Download image to retrieve dimensions and create an ImageInfo object
        with the complete information on the image. """
    ses = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=Retry(backoff_factor=1))
    ses.mount('http://', adapter)
    ses.mount('https://', adapter)
    resp = None
    try:
        resp = ses.get(location, allow_redirects=True, stream=True)
    except Exception as e:
        raise MetsImportError(
            "Could not get image from {}".format(location),
            {'location': location,
             'mimetytpe': mimetype})
    if jpeg_only and resp.headers['Content-Type'] not in JPEG_MIMES:
        return None
    try:
        # We cannot trust the mimetype from the METS, often it lies about
        # what's actually on the server
        server_mime = resp.headers['Content-Type']
        # TODO: Log a warning if mimetype and server_mime mismatch
        img = Image.open(io.BytesIO(resp.content))
        return ImageInfo(id_, location, server_mime, img.width, img.height)
    except OSError as exc:
        raise MetsImportError(
            "Could not open image from {}, likely the server "
            "sent corrupt data.".format(location),
            {'location': location,
             'mimetype': server_mime}) from exc
