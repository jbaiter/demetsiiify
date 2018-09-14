import pytest
import requests_mock

from demetsiiify import imgfetch
from demetsiiify.mets import ImageInfo


def test_add_image_sizes(shared_datadir, monkeypatch):
    # Mock out the HTTP adapter
    with (shared_datadir / 'test.jpg').open('rb') as fp:
        img_bytes = fp.read()
    mock_adapter = requests_mock.Adapter()
    mock_adapter.register_uri(
        'GET', requests_mock.ANY, content=img_bytes,
        status_code=200, headers={'Content-Type': 'image/jpeg'})
    monkeypatch.setattr(imgfetch, 'http_adapter',  mock_adapter)

    mock_files = [ImageInfo(str(idx), f'http://example.com/test-{idx}.jpg')
                  for idx in range(16)]
    mock_files[8].width = 1337
    mock_files[8].height = 2674
    mock_files[8].mimetype = 'image/jpeg'
    last_cur = 0
    for cur, total in imgfetch.add_image_dimensions(mock_files):
        assert cur == last_cur + 1
        assert total == 15
        last_cur = cur
    for idx, f in enumerate(mock_files):
        if idx == 8:
            assert f.width == 1337
            assert f.height == 2674
        else:
            assert f.width == 1024
            assert f.height == 1519
        assert f.mimetype == 'image/jpeg'


def test_add_image_sizes_http_error(shared_datadir, monkeypatch):
    with (shared_datadir / 'test.jpg').open('rb') as fp:
        img_bytes = fp.read()
    mock_adapter = requests_mock.Adapter()
    mock_adapter.register_uri(
        'GET', requests_mock.ANY, content=img_bytes,
        status_code=200, headers={'Content-Type': 'image/jpeg'})
    mock_adapter.register_uri(
        'GET', '/test-12.jpg',
        status_code=500, json={'error': 'some error'})
    monkeypatch.setattr(imgfetch, 'http_adapter',  mock_adapter)
    mock_files = [ImageInfo(str(idx), f'http://example.com/test-{idx}.jpg')
                  for idx in range(16)]

    successful = 0
    with pytest.raises(imgfetch.ImageDownloadError):
        for _ in imgfetch.add_image_dimensions(mock_files):
            successful += 1
    assert successful == 15
