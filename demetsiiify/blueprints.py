import functools
import json
import mimetypes
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, g, jsonify, make_response,
                   redirect, render_template, request, url_for)

from . import make_queues, make_redis
from .models import Manifest, IIIFImage
from .tasks import import_mets_job


view = Blueprint('view', __name__)
api = Blueprint('api', __name__)
iiif = Blueprint('iiif', __name__)


def _get_redis():
    if not hasattr(g, 'redis'):
        g.redis = make_redis()
    return g.redis


queue, failed_queue = make_queues(_get_redis())


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
@view.route('/view/<manifest_id>', methods=['GET'])
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
    return render_template('index.html')


# API Endpoints
@api.route('/api/import', methods=['POST'])
def api_import():
    mets_url = request.json.get('url')
    job = queue.enqueue(import_mets_job, mets_url)
    status_url = url_for('api.api_task_status', task_id=job.id,
                         _external=True)
    response = jsonify({
        'task_id': job.id,
        'status_url': status_url,
        'sse_channel': url_for('api.sse_stream', task_id=job.id,
                               _external=True)})
    response.status_code = 202
    response.headers['Location'] = status_url
    return response


def _get_job_status(job_id):
    job = queue.fetch_job(job_id)
    if job is None:
        job = failed_queue.fetch_job(job_id)
    if job is None:
        return None
    status = job.get_status()
    if status == 'failed':
        exc = job.result
        info = {'message': str(exc),
                'type': type(exc).__name__}
    else:
        info = job.meta
    job_ids = queue.get_job_ids()
    return {'id': job_id,
            'status': status,
            'info': info,
            'position': job_ids.index(job_id) if job_id in job_ids else None,
            'result': job.result if status == 'finished' else None}


@api.route('/api/tasks/<task_id>', methods=['GET'])
def api_task_status(task_id):
    status = _get_job_status(task_id)
    if status:
        return jsonify(status)
    else:
        abort(404)


@api.route('/api/tasks/<task_id>/stream')
def sse_stream(task_id):
    redis = _get_redis()

    def gen(redis):
        channel_name = '__keyspace@0__:rq:job:{}'.format(task_id)
        pubsub = redis.pubsub()
        pubsub.subscribe(channel_name)
        for msg in pubsub.listen():
            status = _get_job_status(task_id)
            ev = ServerSentEvent(status)
            yield ev.encode()
    return current_app.response_class(gen(redis), mimetype="text/event-stream")


# IIIF Endpoints
@iiif.route('/iiif/<manif_uuid>/manifest.json')
@iiif.route('/iiif/<manif_uuid>/manifest')
@cors('*')
def get_manifest(manif_uuid):
    manifest = Manifest.get(manif_uuid)
    if manifest is None:
        abort(404)
    else:
        return jsonify(manifest.manifest)


@iiif.route('/iiif/<manif_uuid>/sequence/<sequence_id>.json')
@iiif.route('/iiif/<manif_uuid>/sequence/<sequence_id>')
@cors('*')
def get_sequence(manif_uuid, sequence_id):
    sequence = Manifest.get_sequence(manif_uuid, sequence_id)
    if sequence is None:
        abort(404)
    else:
        return jsonify(sequence)


@iiif.route('/iiif/<manif_uuid>/canvas/<canvas_id>.json')
@iiif.route('/iiif/<manif_uuid>/canvas/<canvas_id>')
@cors('*')
def get_canvas(manif_uuid, canvas_id):
    canvas = Manifest.get_canvas(manif_uuid, canvas_id)
    if canvas is None:
        abort(404)
    else:
        return jsonify(canvas)


@iiif.route('/iiif/<manif_uuid>/annotation/<anno_id>.json')
@iiif.route('/iiif/<manif_uuid>/annotation/<anno_id>')
@cors('*')
def get_image_annotation(manif_uuid, anno_id):
    anno = Manifest.get_image_annotation(manif_uuid, anno_id)
    if anno is None:
        abort(404)
    else:
        return jsonify(anno)


@iiif.route('/iiif/<manif_uuid>/range/<range_id>.json')
@iiif.route('/iiif/<manif_uuid>/range/<range_id>')
@cors('*')
def get_range(manif_uuid, range_id):
    range_ = Manifest.get_range(manif_uuid, range_id)
    if range_ is None:
        abort(404)
    else:
        return jsonify(range_)


@iiif.route('/iiif/image/<image_uuid>/info.json')
@cors('*')
def get_image_info(image_uuid):
    img = IIIFImage.get(image_uuid)
    if img is None:
        abort(404)
    else:
        return jsonify(img.info)


@iiif.route(
    '/iiif/image/<image_uuid>/<region>/<size>/<rotation>/<quality>.<format>')
@cors('*')
def get_image(image_uuid, region, size, rotation, quality, format):
    not_supported = (region != 'full'
                     or rotation != '0'
                     or quality not in ('default', 'native'))
    if not_supported:
        abort(501)

    iiif_image = IIIFImage.get(image_uuid)
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
