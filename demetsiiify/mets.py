"""Code for parsing METS files."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional

import shortuuid
from lxml import etree


#: Namespaces that are going to be used during XML parsing
NAMESPACES = {
    'mets': 'http://www.loc.gov/METS/',
    'mods': 'http://www.loc.gov/mods/v3',
    'dv': 'http://dfg-viewer.de/',
    'xlink': 'http://www.w3.org/1999/xlink'}

#: Valid mime types for JPEG images
# For some reason, some libraries use the wrong MIME type...
JPEG_MIMES = ('image/jpeg', 'image/jpg')


# Utility datatypes
@dataclass
class PageInfo:
    """All the information about a page in a METS document."""

    ident: str
    label: str
    image_ident: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ImageInfo:
    """Metadata about an image."""

    id: str
    url: str
    mimetype: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class PhysicalItem:
    """A METS physical item (most often a page)."""

    label: str
    files: Iterable[ImageInfo]


@dataclass
class TocEntry:
    """A table of contents entry."""

    children: List[TocEntry]  # pylint:disable=undefined-variable
    physical_ids: List[str]
    logical_id: str
    label: str
    type: str


@dataclass
class MetsPreview:
    """A short preview of a METS document with just basic metadata."""

    mets_url: str
    label: str
    attribution: Mapping[str, str]
    thumbnail: Optional[str] = None


class MetsParseError(Exception):
    """An exception that occured while parsing a METS file."""

    def __init__(self, message: str, debug_info: dict = None) -> None:
        super().__init__(message)
        self.debug_info = debug_info


class MetsDocument:
    """A parsed METS document.

    Note that this is not a generic METS parser, but currently highly coupled
    to both the METS/MODS profile required by the German 'DFG Viewer' and the
    later use as IIIF metadata (which is **not** intended to be
    machine-readable)
    """

    _tree: etree.ElementTree
    _mods_root: etree.Element
    identifiers: Dict[str, str]
    primary_id: str
    physical_items: Dict[str, PhysicalItem]
    toc_entries: Iterable[TocEntry]
    metadata: dict
    files: Dict[str, ImageInfo]

    @classmethod
    def from_url(cls, mets_url: str) -> MetsDocument:
        """Parse a METS document located at the  URL."""
        return MetsDocument(mets_tree=etree.parse(mets_url), url=mets_url)

    def __init__(self, mets_tree: etree.ElementTree, url: str = None,
                 primary_id: str = None) -> None:
        """Parse a METS document.

        This will read the metadata, table of contents and general
        file informations. The width and heights of the images is
        not determined.
        """
        self.url = url
        self._tree = mets_tree
        self._mods_root = self._xpath("(.//mods:mods)[1]")[0]

        self.identifiers = {
            e.get('type'): e.text
            for e in self._xpath("./mods:identifier", self._mods_root)}
        recordid_elem = self._find(
            ".//mods:recordInfo/mods:recordIdentifier", self._mods_root)
        if recordid_elem is not None:
            key = recordid_elem.get('source')
            self.identifiers[key] = recordid_elem.text
        self.primary_id = primary_id or self._get_unique_identifier()
        self.metadata = self._read_metadata()
        self.files = self._read_files()
        self.physical_items = self._read_physical_items()
        self.toc_entries = self._read_toc_entries()

    @property
    def pages(self) -> Iterable[PageInfo]:
        """Return the pages contained in the METS document."""
        for ident, phys_itm in self.physical_items.items():
            width, height = max((f.width, f.height) for f in phys_itm.files)
            yield PageInfo(ident, phys_itm.label, width=width, height=height)

    def _xpath(self, xpath: str,
               elem: etree.Element = None) -> List[etree.Element]:
        elem = elem if elem is not None else self._tree
        return elem.xpath(xpath, namespaces=NAMESPACES)

    def _find(self, path: str, elem: etree.Element = None) -> etree.Element:
        elem = elem if elem is not None else self._tree
        return elem.find(path, namespaces=NAMESPACES)

    def _findall(self, path: str,
                 elem: etree.Element = None) -> List[etree.Element]:
        elem = elem if elem is not None else self._tree
        return elem.findall(path, namespaces=NAMESPACES)

    def _findtext(self, path: str, elem: etree.Element = None) -> str:
        elem = elem if elem is not None else self._tree
        return elem.findtext(path, namespaces=NAMESPACES)

    def _parse_title(self, title_elem: etree.Element) -> str:
        title = self._findtext(".//mods:title", title_elem)
        nonsort = self._findtext(".//mods:nonSort", title_elem)
        if nonsort:
            title = nonsort + title
        subtitle = self._findtext(".//mods:subTitle", title_elem)
        if subtitle:
            title = f"{title}. {subtitle}"
        return title

    def _parse_name(self, name_elem: etree.Element) -> str:
        name = self._findtext("./mods:displayForm", name_elem)
        if not name:
            name = " ".join(
                e.text for e in self._findall("./mods:namePart", name_elem))
        return name

    def _read_persons(self) -> Mapping[str, List[str]]:
        persons: Mapping[str, List[str]] = defaultdict(list)
        name_elems = self._xpath("./mods:name", self._mods_root)
        for e in name_elems:
            name = self._parse_name(e)
            role = self._findtext("./mods:role/mods:roleTerm", e)
            if role == 'aut':
                persons['creator'].append(name)
            else:
                persons['other_persons'].append(name)
        return persons

    def _read_origin(self) -> Mapping[str, str]:
        info_elem = self._find("./mods:originInfo", self._mods_root)
        return {
            'publisher': self._findtext("./mods:publisher", info_elem),
            'pub_place': self._findtext("./mods:place/mods:placeTerm",
                                        info_elem),
            'pub_date': self._findtext("./mods:dateIssued", info_elem)}

    def _get_unique_identifier(self) -> str:
        identifier = ''
        for type_ in ('oai', 'urn'):
            # Identifiers that are intended to be globally unique
            if identifier:
                break
            identifier = self._findtext(f"./mods:identifier[@type='{type_}']",
                                        self._mods_root)
        if not identifier:
            # MODS recordIdentifier, usually available on ZVDD documents
            identifier = self._findtext(
                "./mods:recordInfo/mods:recordIdentifier",
                self._mods_root)
        if not identifier:
            # Random identifier
            identifier = shortuuid.uuid()
        return identifier

    def _read_titles(self) -> List[str]:
        title_elems = self._findall("./mods:titleInfo", self._mods_root)
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
            titles = [f"{title} ({part_number})" for title in titles]
        return titles

    def _read_metadata(self) -> dict:
        metadata: dict = {}
        metadata.update(self._read_persons())
        metadata.update(self._read_origin())
        metadata['title'] = self._read_titles()

        owner_url = self._findtext(".//mets:rightsMD//dv:ownerSiteURL")
        owner = self._findtext(".//mets:rightsMD//dv:owner")
        if owner_url:
            metadata['attribution'] = (
                f"<a href='{owner_url}'>{owner or owner_url}</a>")
        elif owner:
            metadata['attribution'] = owner
        else:
            metadata['attribution'] = 'Unknown'
        metadata['logo'] = self._findtext(
            ".//mets:rightsMD//dv:ownerLogo")

        metadata['see_also'] = []
        if self.url:
            metadata['see_also'].append(
                [{'@id': self.url, 'format': 'text/xml',
                  'profile': 'http://www.loc.gov/METS/'}])
        pdf_url = self._xpath(
            ".//mets:fileGrp[@USE='DOWNLOAD']/"
            "mets:file[@MIMETYPE='application/pdf']/"
            "mets:FLocat/@xlink:href")
        if pdf_url and len(pdf_url) == 1:
            metadata['see_also'].append(
                {'@id': pdf_url, 'format': 'application/pdf'})
        metadata['related'] = self._findtext(
            ".//mets:digiprovMD//dv:presentation")
        license_ = self._findtext(".//dv:rights/dv:license")
        if not license_:
            license_ = self._findtext(".//mods:accessCondition")
        if not license_:
            license_ = 'reserved'
        metadata['license'] = license_

        # TODO: mods:physicalDescription
        metadata['language'] = self._findtext(
            ".//mods:languageTerm[@type='text']")
        metadata['genre'] = self._findtext(".//mods:genre")
        metadata['description'] = self._findtext(".//mods:abstract") or ""

        # TODO: Add mods:notes to description
        return metadata

    def _read_files(self) -> Dict[str, ImageInfo]:
        img_specs = (self._get_image_specs(e)
                     for e in self._findall(".//mets:file"))
        return {info.id: info for info in img_specs
                if info.url and info.url.startswith('http')}

    def _read_physical_items(self) -> Dict[str, PhysicalItem]:
        """Create a map from physical IDs to (label, image_info) pairs."""
        if self.files is None:
            raise ValueError(
                "Can't read physical items before files have been read.")
        physical_items = {}
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
            physical_items[page_id] = PhysicalItem(
                label, [f for f in files if f is not None])
        return physical_items

    def _parse_tocentry(self, toc_elem: etree.Element,
                        lmap: Mapping[str, List[str]]) -> TocEntry:
        """Parse a toc entry subtree to a MetsTocEntry object."""
        log_id = toc_elem.get('ID')
        entry = TocEntry(
            children=[], physical_ids=lmap.get(log_id, []),
            type=toc_elem.get('TYPE'),
            logical_id=log_id, label=toc_elem.get('LABEL'))
        for e in self._findall("./mets:div", toc_elem):
            entry.children.append(self._parse_tocentry(e, lmap))
        return entry

    def _read_toc_entries(self) -> List[TocEntry]:
        """Create trees of TocEntries from the METS."""
        toc_entries = []
        lmap: Dict[str, List[str]] = {}
        mappings = [
            (e.get('{%s}from' % NAMESPACES['xlink']),
             e.get('{%s}to' % NAMESPACES['xlink']))
            for e in self._findall(".//mets:structLink//mets:smLink")]
        for logical_id, physical_id in mappings:
            if logical_id not in lmap:
                lmap[logical_id] = []
            lmap[logical_id].append(physical_id)
        for e in self._xpath(".//mets:structMap[@TYPE='LOGICAL']/mets:div"):
            toc_entries.append(self._parse_tocentry(e, lmap))
        return toc_entries

    def _get_image_specs(self, file_elem: etree.Element) -> ImageInfo:
        image_id = file_elem.get('ID')
        mimetype = file_elem.get('MIMETYPE')
        location = self._xpath(
            "./mets:FLocat[@LOCTYPE='URL']/@xlink:href", file_elem)
        return ImageInfo(image_id, location[0] if location else None, mimetype)
