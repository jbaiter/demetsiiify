import functools
import mimetypes
import os
import time
from collections import deque, OrderedDict
from urllib.parse import urlparse

import lxml.etree as ET
import shortuuid
from celery import Celery
from flask import (Flask, abort, jsonify, make_response, redirect,
                   render_template, request, url_for)

import iiif
import ingest as mets
from storage import db, Manifest, IIIFImage, Image

DEFAULT_SECRET = """
larencontrefortuitesurunetablededissectiond'unemachineàcoudreetd'unparapluie
"""


def _force_preferred_scheme():
    if app.config['PREFERRED_URL_SCHEME'] == 'https':
        from flask import _request_ctx_stack
        if _request_ctx_stack is not None:
            reqctx = _request_ctx_stack.top
            reqctx.url_adapter.url_scheme = 'https'


def make_app():
    app = Flask(__name__)
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get(
        'PREFERRED_URL_SCHEME', 'http')
    app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:5000')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', DEFAULT_SECRET)
    app.config['CELERY_BROKER_URL'] = 'redis://redis:6379/0'
    app.config['CELERY_RESULT_BACKEND'] = 'redis://redis:6379/0'
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'postgresql://postgres:postgres@postgres:5432/postgres')
    return app


def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery


app = make_app()
app.before_request(_force_preferred_scheme)
db.init_app(app)
celery = make_celery(app)


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


# Tasks
@celery.task(bind=True, name='tasks.import_mets')
def import_mets_job(self, mets_url):
    tree = ET.parse(mets_url)
    file_infos = {}
    times = deque(maxlen=50)
    start_time = time.time()
    for img_info, idx, total in mets.get_file_infos(tree, jpeg_only=True):
        duration = time.time() - start_time
        times.append(duration)
        file_infos[img_info.id] = img_info
        self.update_state(
            state='PROGRESS',
            meta={'current_image': idx, 'total_images': total,
                  'eta': (sum(times)/len(times)) * (total - idx)})
        start_time = time.time()
    phys_map = mets.physical_map(tree, file_infos)
    iiif_map = OrderedDict()
    thumbs_map = {}
    for phys_id, (label, files) in phys_map.items():
        image_ident = shortuuid.uuid()
        largest_image = max(files, key=lambda f: f.height)
        smallest_image = min(files, key=lambda f: f.height)
        iiif_info = iiif.make_info_data(
            image_ident, [(f.width, f.height) for f in files])
        db_iiif_img = IIIFImage(iiif_info, uuid=image_ident)
        IIIFImage.save(db_iiif_img)
        for f in files:
            db_img = Image(f.url, f.width, f.height, f.mimetype, image_ident)
            Image.save(db_img)
        iiif_map[phys_id] = (image_ident, label,
                             (largest_image.width, largest_image.height))
        thumbs_map[image_ident] = (smallest_image.width, smallest_image.height)
    metadata = mets.get_metadata(tree)
    toc_entries = mets.toc_entries(tree)
    manifest_id = shortuuid.uuid()
    manifest = iiif.make_manifest(manifest_id, tree, metadata, iiif_map,
                                  toc_entries, thumbs_map)
    db_manifest = Manifest(mets_url, manifest, uuid=manifest_id,
                           label=manifest['label'])
    Manifest.save(db_manifest)
    # Since the METS might have already been indexed, there's the possibility
    # that the IIIF images might have changed, leading to orphaned images.
    IIIFImage.delete_orphaned()
    db.session.commit()
    return manifest['@id']


# View endpoints
@app.route('/view/<path:mets>', methods=['GET'])
def view_endpoint(mets):
    if is_url(mets):
        manifest = Manifest.by_url(mets)
    else:
        manifest = Manifest.get(mets)
    if is_url(mets) and manifest is None:
        task = import_mets_job.apply_async((mets,))
        return redirect(url_for('view_status', task_id=task.id,
                                _external=True), code=202)
    elif manifest:
        return render_template('viewer', manifest_id=manifest['@id'])
    else:
        abort(404)


@app.route('/')
def index():
    return jsonify({'scheme': app.config['PREFERRED_URL_SCHEME'],
                    'server_name': app.config['SERVER_NAME']})


@app.route('/status/<task_id>')
def view_status(task_id):
    return render_template('status', task_id=task_id)


# API Endpoints
@app.route('/api/import', methods=['POST'])
def api_import():
    mets_url = request.json.get('url')
    task = import_mets_job.apply_async((mets_url,))
    status_url = url_for('api_task_status', task_id=task.id, _external=True)
    response = jsonify({'status': status_url})
    response.status_code = 202
    response.headers['Location'] = status_url
    return response


@app.route('/api/tasks/<task_id>', methods=['GET'])
def api_task_status(task_id):
    task = import_mets_job.AsyncResult(task_id)
    if task is None:
        abort(404)
    if isinstance(task.info, Exception):
        info = {'message': str(task.info),
                'type': type(task.info).__name__}
    else:
        info = task.info
    return jsonify(
        {'status': task.state,
         'info': info,
         'result': task.get() if task.state == 'SUCCESS' else None})


@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_remove_task(task_id):
    task = import_mets_job.AsyncResult(task_id)
    if task is None:
        abort(404)
    task.revoke(request.args.get('terminate') is not None)


# IIIF Endpoints
@app.route('/iiif/<manif_uuid>/manifest.json')
@app.route('/iiif/<manif_uuid>/manifest')
@cors('*')
def get_manifest(manif_uuid):
    manifest = Manifest.get(manif_uuid)
    if manifest is None:
        abort(404)
    else:
        return jsonify(manifest.manifest)


@app.route('/iiif/<manif_uuid>/sequence/<sequence_id>.json')
@app.route('/iiif/<manif_uuid>/sequence/<sequence_id>')
@cors('*')
def get_sequence(manif_uuid, sequence_id):
    sequence = Manifest.get_sequence(manif_uuid, sequence_id)
    if sequence is None:
        abort(404)
    else:
        return jsonify(sequence)


@app.route('/iiif/<manif_uuid>/canvas/<canvas_id>.json')
@app.route('/iiif/<manif_uuid>/canvas/<canvas_id>')
@cors('*')
def get_canvas(manif_uuid, canvas_id):
    canvas = Manifest.get_canvas(manif_uuid, canvas_id)
    if canvas is None:
        abort(404)
    else:
        return jsonify(canvas)


@app.route('/iiif/<manif_uuid>/annotation/<anno_id>.json')
@app.route('/iiif/<manif_uuid>/annotation/<anno_id>')
@cors('*')
def get_image_annotation(manif_uuid, anno_id):
    anno = Manifest.get_image_annotation(manif_uuid, anno_id)
    if anno is None:
        abort(404)
    else:
        return jsonify(anno)


@app.route('/iiif/<manif_uuid>/range/<range_id>.json')
@app.route('/iiif/<manif_uuid>/range/<range_id>')
@cors('*')
def get_range(manif_uuid, range_id):
    range_ = Manifest.get_range(manif_uuid, range_id)
    if range_ is None:
        abort(404)
    else:
        return jsonify(range_)


@app.route('/iiif/image/<image_uuid>/info.json')
@cors('*')
def get_image_info(image_uuid):
    img = IIIFImage.get(image_uuid)
    if img is None:
        abort(404)
    else:
        return jsonify(img.info)


@app.route(
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


if __name__ == '__main__':
    app.run(host='0.0.0.0')
