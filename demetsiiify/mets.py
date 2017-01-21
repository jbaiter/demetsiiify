import io
from collections import OrderedDict, namedtuple, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

import lxml.etree as etree
import requests
import shortuuid
from flask import current_app
from PIL import Image
from requests.packages.urllib3 import Retry

from . import models
from .iiif import make_label

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
        return cls(etree.parse(metsurl), url=metsurl)

    def __init__(self, mets_tree, primary_id=None, url=None):
        self.url = url
        self._tree = mets_tree
        self._rootmods = self._xpath("(.//mods:mods)[1]")[0]

        self.identifiers = {
            e.get('type'): e.text
            for e in self._xpath("./mods:identifier", self._rootmods)}
        recordid_elem = self._find(
            ".//mods:recordInfo/mods:recordIdentifier", self._rootmods)
        if recordid_elem is not None:
            key = recordid_elem.get('source')
            self.identifiers[key] = recordid_elem.text
        self.primary_id = primary_id or self._get_unique_identifier()

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
            name = " ".join(
                e.text for e in self._findall("./mods:namePart", name_elem))
        return name

    def _read_persons(self):
        persons = defaultdict(list)
        name_elems = self._xpath("./mods:name", self._rootmods)
        for e in name_elems:
            name = self._parse_name(e)
            role = self._findtext("./mods:role/mods:roleTerm", e)
            if role == 'aut':
                persons['creator'].append(name)
            else:
                persons['other_persons'].append(name)
        return persons

    def _read_origin(self):
        info_elem = self._find("./mods:originInfo", self._rootmods)
        return {
            'publisher': self._findtext("./mods:publisher", info_elem),
            'pub_place': self._findtext("./mods:place/mods:placeTerm",
                                        info_elem),
            'pub_date': self._findtext("./mods:dateIssued", info_elem)}

    def _get_unique_identifier(self):
        identifier = None
        for type_ in ('oai', 'urn'):
            # Identifiers that are intended to be globally unique
            if identifier:
                break
            identifier = self._findtext(
                "./mods:identifier[@type='{}']".format(type_),
                self._rootmods)
        if not identifier:
            # MODS recordIdentifier, usually available on ZVDD documents
            identifier = self._findtext(
                "./mods:recordInfo/mods:recordIdentifier",
                self._rootmods)
        if not identifier:
            # Random identifier
            identifier = shortuuid.uuid()
        return identifier

    def _read_titles(self):
        title_elems = self._findall("./mods:titleInfo", self._rootmods)
        if not title_elems:
            # For items with no title of their own that are part of a larger
            # multi-volume work
            title_elems = [self._findall(
                ".//mods:relatedItem[@type='host']/mods:titleInfo")[0]]
        # TODO: Use information from table of contents to find out about
        #       titles of multi-volume work
        titles = [self._parse_title(e) for e in title_elems]
        part_number = self._findtext(".//mods:part/mods:detail/mods:number")
        if part_number:
            titles = [
                "{title} ({part_no})".format(title=title, part_no=part_number)
                for title in titles]
        return titles

    def read_metadata(self):
        self.metadata.update(self._read_persons())
        self.metadata.update(self._read_origin())
        self.metadata['title'] = self._read_titles()

        owner_url = self._findtext(".//mets:rightsMD//dv:ownerSiteURL")
        owner = self._findtext(".//mets:rightsMD//dv:owner")
        if owner_url:
            self.metadata['attribution'] = "<a href='{}'>{}</a>".format(
                owner_url, owner or owner_url)
        elif owner:
            self.metadata['attribution'] = owner
        else:
            self.metadata['attribution'] = 'Unknown'
        self.metadata['logo'] = self._findtext(
            ".//mets:rightsMD//dv:ownerLogo")

        self.metadata['see_also'] = []
        if self.url:
            self.metadata['see_also'].append(
                [{'@id': self.url, 'format': 'text/xml',
                  'profile': 'http://www.loc.gov/METS/'}])
        pdf_url = self._xpath(
            ".//mets:fileGrp[@USE='DOWNLOAD']/"
            "mets:file[@MIMETYPE='application/pdf']/"
            "mets:FLocat/@xlink:href")
        if pdf_url and len(pdf_url) == 1:
            self.metadata['see_also'].append(
                {'@id': pdf_url, 'format': 'application/pdf'})
        self.metadata['related'] = self._findtext(
            ".//mets:digiprovMD//dv:presentation")
        license = self._findtext(".//dv:rights/dv:license")
        if not license:
            license = self._findtext(".//mods:accessCondition")
        if not license:
            license = 'reserved'
        self.metadata['license'] = license

        # TODO: mods:physicalDescription
        self.metadata['language'] = self._findtext(
            ".//mods:languageTerm[@type='text']")
        self.metadata['genre'] = self._findtext(".//mods:genre")
        self.metadata['description'] = self._findtext(".//mods:abstract") or ""
        # TODO: Add mods:notes to description

    def read_files(self, jpeg_only=False, yield_progress=True, concurrency=2):
        about_url = "{}://{}/about".format(
            current_app.config['PREFERRED_URL_SCHEME'],
            current_app.config['SERVER_NAME'])
        # FIXME: This is still way too messy!
        self.files = OrderedDict()
        mets_info = [
            (id_, location, mimetype)
            for id_, location, mimetype in
            (self._get_image_specs(e) for e in self._findall(".//mets:file"))
            if location and location.startswith('http')]
        with ThreadPoolExecutor(max_workers=concurrency or 1) as pool:
            futs = []
            for id_, loc, mime, in mets_info:
                db_info = models.Image.by_url(loc)
                if db_info is None:
                    futs.append(pool.submit(
                        image_info, id_, loc, mime, jpeg_only=True,
                        about_url=about_url))
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
                if label:
                    break
            if not label:
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
        location = self._xpath(
            "./mets:FLocat[@LOCTYPE='URL']/@xlink:href", felem)
        if location:
            location = location[0]
        else:
            location = None
        return image_id, location, mimetype


def image_info(id_, location, mimetype, jpeg_only=False, about_url=None):
    """ Download image to retrieve dimensions and create an ImageInfo object
        with the complete information on the image. """
    ses = requests.Session()
    if about_url:
        ses.headers = {'User-Agent': 'demetsiiify <{}>'.format(about_url)}
    adapter = requests.adapters.HTTPAdapter(
        max_retries=Retry(backoff_factor=1))
    ses.mount('http://', adapter)
    ses.mount('https://', adapter)
    resp = None
    try:
        # We open it streaming, since we don't neccessarily have to read
        # the complete response (e.g. if the MIME type is unsuitable)
        resp = ses.get(location, allow_redirects=True, stream=True,
                       timeout=30)
    except Exception as e:
        resp = None
    if not resp:
        raise MetsImportError(
            "Could not get image from {}, error_code was {}"
            .format(location, resp.status_code),
            {'location': location,
             'mimetytpe': mimetype})
    # We cannot trust the mimetype from the METS, sometimes it lies about
    # what's actually on the server
    server_mime = resp.headers['Content-Type'].split(';')[0]
    if jpeg_only and server_mime not in JPEG_MIMES:
        return None
    server_mime = server_mime.replace('jpg', 'jpeg')
    try:
        # TODO: Log a warning if mimetype and server_mime mismatch
        img = Image.open(io.BytesIO(resp.content))
        return ImageInfo(id_, location, server_mime, img.width, img.height)
    except OSError as exc:
        raise MetsImportError(
            "Could not open image from {}, likely the server "
            "sent corrupt data.".format(location),
            {'location': location,
             'mimetype': server_mime}) from exc


def get_basic_info(mets_url):
    tree = etree.parse(mets_url)
    doc = MetsDocument(tree, url=mets_url)
    doc.read_metadata()
    thumb_urls = doc._xpath(
        ".//mets:file[@MIMETYPE='image/jpeg']/mets:FLocat/@xlink:href")
    if not thumb_urls:
        thumb_urls = doc._xpath(
            ".//mets:file[@MIMETYPE='image/jpg']/mets:FLocat/@xlink:href")
    return {
        'metsurl': mets_url,
        'label': make_label(doc.metadata),
        'thumbnail': thumb_urls[0] if thumb_urls else None,
        'attribution': {
            'logo': doc.metadata['logo'],
            'owner': doc.metadata['attribution']
        }
    }
