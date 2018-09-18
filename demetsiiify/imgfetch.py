"""Logic for downloading images."""
import io
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Iterable, Tuple

import requests
from PIL import Image
from urllib3.util.retry import Retry

from . import models
from .mets import ImageInfo

#: Adapter for HTTP requests
http_adapter = requests.adapters.HTTPAdapter(
    max_retries=Retry(backoff_factor=1))


#: Valid mime types for JPEG images
# For some reason, some libraries use the wrong MIME type...
JPEG_MIMES = ('image/jpeg', 'image/jpg')


#: Progress type: (current, total)
Progress = Tuple[int, int]


class ImageDownloadError(Exception):
    """An error that occured while downloading an image."""

    def __init__(self, message: str, debug_info: dict = None) -> None:
        super().__init__(message)
        self.debug_info = debug_info


def _complete_image_info(
        file: ImageInfo, jpeg_only: bool = False, about_url=None) -> None:
    """Download image to retrieve dimensions."""
    ses = requests.Session()
    if about_url:
        ses.headers = {'User-Agent': f'demetsiiify <{about_url}>'}
    ses.mount('http://', http_adapter)
    ses.mount('https://', http_adapter)
    resp = None
    if file.mimetype not in JPEG_MIMES:
        return
    try:
        # We open it streaming, since we don't necessarily have to read
        # the complete response (e.g. if the MIME type is unsuitable)
        resp = ses.get(file.url, allow_redirects=True, stream=True,
                       timeout=30)
    except Exception as exc:
        raise ImageDownloadError(
            f"Could not get image from {file.url}: {exc}",
            {'location': file.url, 'error': str(exc)}) from exc
    if not resp:
        raise ImageDownloadError(
            f"Could not get image from {file.url}, "
            f"error_code was {resp.status_code}",
            {'location': file.url,
             'mimetytpe': file.mimetype})
    # We cannot trust the mimetype from the METS, sometimes it lies about
    # what's actually on the server
    server_mime = resp.headers['Content-Type'].split(';')[0]
    if jpeg_only and server_mime not in JPEG_MIMES:
        return
    server_mime = server_mime.replace('jpg', 'jpeg')
    try:
        # TODO: Log a warning if mimetype and server_mime mismatch
        img = Image.open(io.BytesIO(resp.content))
        file.width = img.width
        file.height = img.height
        file.mimetype = server_mime
    except OSError as exc:
        raise ImageDownloadError(
            f"Could not open image from {file.url}, likely the server "
            f"sent corrupt data.",
            {'location': file.url,
             'mimetype': server_mime}) from exc


def add_image_dimensions(
        files: Iterable[ImageInfo], jpeg_only: bool = True,
        about_url: str = None, concurrency: int = 2) -> Iterable[Progress]:
    """Download files to add image dimension information."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = []
        for file in files:
            if file.width is not None and file.height is not None:
                continue
            futs.append(pool.submit(
                _complete_image_info, file, jpeg_only=jpeg_only,
                about_url=about_url))
        exc = None
        for idx, fut in enumerate(as_completed(futs), start=1):
            try:
                fut.result()
                yield idx, len(futs)
            except Exception as e:
                exc = e
        # This will wait until all other images have been downloaded and only
        # then raise an exception. This way we can decide if we want to cancel
        # completely downstream or not
        if exc is not None:
            raise ImageDownloadError(
                "Could not get image dimensions.") from exc
