import pytest
import shortuuid
from lxml import etree

from demetsiiify import iiif, mets


def _add_mock_sizes(mets_doc):
    for itm in mets_doc.physical_items.values():
        w, h = (256, 256)
        itm.image_ident = shortuuid.uuid()
        for f in itm.files:
            f.width = w
            f.height = h
            w = w * 2
            h = h * 2


def test_make_manifest(shared_datadir):
    mets_tree = etree.parse(
        str(shared_datadir / 'urn:nbn:de:gbv:23-drucke_li-1876-12.xml'))
    mets_doc = mets.MetsDocument(mets_tree)
    _add_mock_sizes(mets_doc)
    manif = iiif.make_manifest(
        ident='test',
        mets_doc=mets_doc,
        base_url='https://example.iiif')
    import json
    with open('/tmp/test.json', 'wt') as fp:
        json.dump(manif, fp, indent=2)

    # No null/empty values in metadata
    for meta in manif['metadata']:
        assert meta['value']

    # All canvases are there
    assert len(manif['sequences'][0]['canvases']) == 904
