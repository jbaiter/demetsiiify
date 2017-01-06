import functools
import json
import logging
import mimetypes
from urllib.parse import urlparse

import lxml.etree as ET
import requests
from flask import (Blueprint, abort, current_app, jsonify, make_response,
                   redirect, render_template, request, url_for)
from validate_email import validate_email

from . import mets
from .models import Identifier, Manifest, IIIFImage
from .tasks import queue, failed_queue, get_redis, import_mets_job
from .iiif import make_manifest_collection, make_label


view = Blueprint('view', __name__)
api = Blueprint('api', __name__)
iiif = Blueprint('iiif', __name__)


class ServerSentEvent(object):
    def __init__(self, data):
        if not isinstance(data, str):
            data = json.dumps(data)
        self.data = data
        self.event = None
        self.id = None
        self.desc_map = {
            self.data: "data",
            self.event: "event",
            self.id: "id"}

    def encode(self):
        if not self.data:
            return ""
        lines = ["%s: %s" % (v, k)
                 for k, v in self.desc_map.items() if k]
        return "%s\n\n" % "\n".join(lines)


def is_url(value):
    return bool(urlparse.urlparse(value).scheme)


def cors(origin='*'):
    """This decorator adds CORS headers to the response"""
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            resp = make_response(f(*args, **kwargs))
            h = resp.headers
            h['Access-Control-Allow-Origin'] = origin
            return resp
        return decorated_function
    return decorator


# View endpoints
@view.route('/view/<path:manifest_id>', methods=['GET'])
def view_endpoint(manifest_id):
    manifest = Manifest.get(manifest_id)
    if manifest is None:
        abort(404)
    else:
        return render_template('view.html',
                               label=manifest.manifest['label'],
                               manifest_uri=manifest.manifest['@id'])


@view.route('/')
def index():
    return render_template('index.html', latest=_get_latest(10))


def _get_latest(num):
    return list(reversed([
        {'id': m.id,
         'manifest': url_for('iiif.get_manifest', manif_id=m.id,
                             _external=True),
         'preview': m.manifest['sequences'][0]['canvases'][0]['thumbnail'],
         'label': m.label,
         'attribution': m.manifest['attribution'],
         'attribution_logo': m.manifest['logo']}
        for m in Manifest.get_latest(num)]))


# API Endpoints
@api.route('/api/latest')
def api_get_latest():
    num = int(request.args.get('num', '10'))
    return jsonify(dict(latest=_get_latest(num)))


@api.route('/api/resolve/<identifier>')
def api_resolve(identifier):
    manifest_id = Identifier.resolve(identifier)
    if manifest_id is None:
        abort(404)
    else:
        return redirect(url_for('iiif.get_manifest', manif_id=manifest_id))


def _get_basic_info(mets_url):
    tree = ET.parse(mets_url)
    doc = mets.MetsDocument(tree, url=mets_url)
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


@api.route('/api/import', methods=['POST'])
def api_import():
    mets_url = request.json.get('url')
    resp = None
    try:
        resp = requests.head(mets_url)
    except:
        pass
    if not resp:
        return jsonify({
            'message': 'There is no METS available at the given URL.'}), 400
    try:
        job_meta = _get_basic_info(mets_url)
        job = queue.enqueue(import_mets_job, mets_url, meta=job_meta)
        job.refresh()
        status_url = url_for('api.api_task_status', task_id=job.id,
                             _external=True)
        response = jsonify(_get_job_status(job.id))
        response.status_code = 202
        response.headers['Location'] = status_url
    except Exception as e:
        logging.exception(e)
        response = jsonify({'message': str(e)})
        response.status_code = 500
    return response


def _get_job_status(job):
    if isinstance(job, str):
        job = queue.fetch_job(job)
        if job is None:
            job = failed_queue.fetch_job(job)
        if job is None:
            return None
    status = job.get_status()
    out = {'id': job.id,
           'status': status}
    out.update(job.meta)
    if status == 'failed':
        out.update(job.meta)
    elif status == 'queued':
        job_ids = queue.get_job_ids()
        out['position'] = job_ids.index(job.id) if job.id in job_ids else None
    elif status == 'finished':
        out['result'] = job.result
    return out


@api.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    return jsonify(
        {'tasks': [_get_job_status(job_id) for job_id in queue.job_ids]})


@api.route('/api/tasks/<task_id>', methods=['GET'])
def api_task_status(task_id):
    status = _get_job_status(task_id)
    if status:
        return jsonify(status)
    else:
        abort(404)


@api.route('/api/tasks/<task_id>/stream')
def sse_stream(task_id):
    redis = get_redis()
    job = queue.fetch_job(task_id)
    if job is None:
        job = failed_queue.fetch_job(task_id)
    if job is None:
        abort(404)

    def gen(redis):
        channel_name = '__keyspace@0__:rq:job:{}'.format(task_id)
        pubsub = redis.pubsub()
        pubsub.subscribe(channel_name)
        last_evt = None
        for msg in pubsub.listen():
            status = _get_job_status(task_id)
            evt = ServerSentEvent(status).encode()
            if evt != last_evt:
                yield evt
            last_evt = evt
    return current_app.response_class(gen(redis), mimetype="text/event-stream")


@api.route('/api/tasks/notify', methods=['POST'])
def register_email_notification():
    recipient = request.json['recipient']
    job_ids = request.json['jobs']
    if not validate_email(recipient, verify=True):
        return jsonify({'error': 'The email passed is not valid!'}), 400
    redis = get_redis()
    jobs_key = 'notifications.{}.jobs'.format(recipient)
    batch = redis.pipeline()
    batch.sadd(jobs_key, *job_ids)
    for job_id in job_ids:
        batch.sadd('recipients.{}'.format(job_id), recipient)
    batch.execute()
    return jsonify({'jobs': [e.decode('utf8')
                             for e in redis.smembers(jobs_key)]})


# IIIF Endpoints
@iiif.route('/iiif/collection/<collection_id>/<page_id>')
@cors('*')
def get_collection(collection_id, page_id):
    if collection_id != 'index':
        abort(404)
    if page_id == 'top':
        page_num = None
    else:
        page_num = int(page_id[1:])
    pagination = Manifest.query.paginate(
        page=page_num,
        per_page=current_app.config['ITEMS_PER_PAGE'])
    label = "All manifests available at {}".format(
        current_app.config['SERVER_NAME'])
    return jsonify(make_manifest_collection(
        pagination, label, collection_id, page_num))


@iiif.route('/iiif/<path:manif_id>/manifest.json')
@iiif.route('/iiif/<path:manif_id>/manifest')
@cors('*')
def get_manifest(manif_id):
    manifest = Manifest.get(manif_id)
    if manifest is None:
        abort(404)
    else:
        return jsonify(manifest.manifest)


@iiif.route('/iiif/<path:manif_id>/sequence/<sequence_id>.json')
@iiif.route('/iiif/<path:manif_id>/sequence/<sequence_id>')
@cors('*')
def get_sequence(manif_id, sequence_id):
    sequence = Manifest.get_sequence(manif_id, sequence_id)
    if sequence is None:
        abort(404)
    else:
        return jsonify(sequence)


@iiif.route('/iiif/<path:manif_id>/canvas/<canvas_id>.json')
@iiif.route('/iiif/<path:manif_id>/canvas/<canvas_id>')
@cors('*')
def get_canvas(manif_id, canvas_id):
    canvas = Manifest.get_canvas(manif_id, canvas_id)
    if canvas is None:
        abort(404)
    else:
        return jsonify(canvas)


@iiif.route('/iiif/<path:manif_id>/annotation/<anno_id>.json')
@iiif.route('/iiif/<path:manif_id>/annotation/<anno_id>')
@cors('*')
def get_image_annotation(manif_id, anno_id):
    anno = Manifest.get_image_annotation(manif_id, anno_id)
    if anno is None:
        abort(404)
    else:
        return jsonify(anno)


@iiif.route('/iiif/<path:manif_id>/range/<range_id>.json')
@iiif.route('/iiif/<path:manif_id>/range/<range_id>')
@cors('*')
def get_range(manif_id, range_id):
    range_ = Manifest.get_range(manif_id, range_id)
    if range_ is None:
        abort(404)
    else:
        return jsonify(range_)


@iiif.route('/iiif/image/<image_id>/info.json')
@cors('*')
def get_image_info(image_id):
    img = IIIFImage.get(image_id)
    if img is None:
        abort(404)
    else:
        return jsonify(img.info)


@iiif.route(
    '/iiif/image/<image_id>/<region>/<size>/<rotation>/<quality>.<format>')
@cors('*')
def get_image(image_id, region, size, rotation, quality, format):
    not_supported = (region != 'full'
                     or rotation != '0'
                     or quality not in ('default', 'native'))
    if not_supported:
        abort(501)

    iiif_image = IIIFImage.get(image_id)
    if iiif_image is None:
        abort(404)

    format = mimetypes.types_map.get('.' + format)
    query = dict(format_=format)
    if size not in ('full', 'max'):
        parts = [v for v in size.split(',') if v]
        if size.endswith(','):
            query['width'] = int(parts[0])
        elif size.startswith(','):
            query['height'] = int(parts[0])
        else:
            query['width'], query['height'] = [int(p) for p in parts]
    url = iiif_image.get_image_url(**query)
    if url is None:
        abort(501)
    else:
        return redirect(url, 303)
