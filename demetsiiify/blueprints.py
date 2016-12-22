import functools
import mimetypes
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, jsonify, make_response,
                   redirect, render_template, request, url_for)

from .models import Manifest, IIIFImage


view = Blueprint('view', __name__)
api = Blueprint('api', __name__)
iiif = Blueprint('iiif', __name__)


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
@view.route('/view/<path:mets>', methods=['GET'])
def view_endpoint(mets):
    if is_url(mets):
        manifest = Manifest.by_url(mets)
    else:
        manifest = Manifest.get(mets)
    if is_url(mets) and manifest is None:
        from .tasks import import_mets_job
        task = import_mets_job.apply_async((mets,))
        return redirect(url_for('view.view_status', task_id=task.id,
                                _external=True), code=202)
    elif manifest:
        return render_template('viewer', manifest_id=manifest['@id'])
    else:
        abort(404)


@view.route('/')
def index():
    return jsonify({'scheme': current_app.config['PREFERRED_URL_SCHEME'],
                    'server_name': current_app.config['SERVER_NAME']})


@view.route('/status/<task_id>')
def view_status(task_id):
    return render_template('status', task_id=task_id)


# API Endpoints
@api.route('/api/import', methods=['POST'])
def api_import():
    from .tasks import import_mets_job
    mets_url = request.json.get('url')
    task = import_mets_job.apply_async((mets_url,))
    status_url = url_for('api.api_task_status', task_id=task.id,
                         _external=True)
    response = jsonify({'status': status_url})
    response.status_code = 202
    response.headers['Location'] = status_url
    return response


@api.route('/api/tasks/<task_id>', methods=['GET'])
def api_task_status(task_id):
    from .tasks import import_mets_job
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


@api.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_remove_task(task_id):
    from .tasks import import_mets_job
    task = import_mets_job.AsyncResult(task_id)
    if task is None:
        abort(404)
    task.revoke(request.args.get('terminate') is not None)


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
