from lxml import etree

from demetsiiify import mets


def test_basic_mets(shared_datadir):
    mets_tree = etree.parse(
        str(shared_datadir / 'urn:nbn:de:gbv:23-drucke_li-1876-12.xml'))
    mets_doc = mets.MetsDocument(mets_tree)
    assert len(mets_doc.files) == 3616
    assert all(
        f.id is not None and f.url is not None and f.mimetype == 'image/jpeg'
        for f in mets_doc.files.values())
    assert all(k in mets_doc.identifiers
               for k in ('urn', 'fingerprint', 'vd17', 'purl'))
    assert tuple(mets_doc.metadata['creator']) == ('Dilherr, Johann Michael',)
    assert all(len(p.files) == 4 for p in mets_doc.physical_items.values())

    test_phys = mets_doc.physical_items['struct-physical-idp65132464']
    assert all(f is mets_doc.files[f.id] for f in test_phys.files)
    assert len(mets_doc.toc_entries[0].children) == 30
