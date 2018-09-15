import functools
import mimetypes
import shortuuid

from flask import (Blueprint, abort, current_app, jsonify, make_response,
                   redirect, request, url_for)

from ..extensions import auto, db
from ..iiif import make_manifest_collection, make_annotation_list
from ..models import Annotation, Collection, IIIFImage, Manifest


iiif = Blueprint('iiif', __name__)


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


@iiif.route('/iiif/collection', redirect_to='/iiif/collection/index/top')
@iiif.route('/iiif/collection/<collection_id>',
            redirect_to='/iiif/collection/<collection_id>/top')
@iiif.route('/iiif/collection/<collection_id>/<page_id>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_collection(collection_id='index', page_id='top'):
    """ Get the collection of all IIIF manifests on this server. """
    subcollections = None
    if page_id == 'top':
        page_num = None
    else:
        page_num = int(page_id[1:])
    base_url = "{}://{}".format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'])
    per_page = current_app.config['ITEMS_PER_PAGE']
    if collection_id == 'index':
        manifest_pagination = Manifest.query.paginate(
            page=page_num, per_page=per_page)
        if page_num == 1:
            subcollections = (
                Collection.query.filter_by(parent_collection=None).all())
        label = "Manifests available at {}".format(
            current_app.config['SERVER_NAME'])
    else:
        collection = Collection.get(collection_id)
        if not collection:
            abort(404)
        manifest_pagination = collection.manifests.paginate(
            page=page_num, per_page=per_page)
        label = collection.label
    if page_num == 1:
        coll_counts = Collection.get_child_collection_counts(collection_id)
    return jsonify(make_manifest_collection(
        manifest_pagination, label, collection_id, base_url=base_url,
        page_num=page_num, coll_counts=coll_counts))


@iiif.route('/iiif/<path:manif_id>/manifest.json')
@iiif.route('/iiif/<path:manif_id>/manifest')
@auto.doc(groups=['iiif'])
@cors('*')
def get_manifest(manif_id):
    """ Obtain a single manifest. """
    manifest = Manifest.get(manif_id)
    if manifest is None:
        abort(404)
    else:
        return jsonify(manifest.manifest)


@iiif.route('/iiif/<path:manif_id>/sequence/<sequence_id>.json')
@iiif.route('/iiif/<path:manif_id>/sequence/<sequence_id>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_sequence(manif_id, sequence_id):
    """ Obtain the given sequence from a manifest. """
    sequence = Manifest.get_sequence(manif_id, sequence_id)
    if sequence is None:
        abort(404)
    else:
        return jsonify(sequence)


@iiif.route('/iiif/<path:manif_id>/canvas/<canvas_id>.json')
@iiif.route('/iiif/<path:manif_id>/canvas/<canvas_id>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_canvas(manif_id, canvas_id):
    """ Obtain the given canvas from a manifest. """
    canvas = Manifest.get_canvas(manif_id, canvas_id)
    if canvas is None:
        abort(404)
    else:
        return jsonify(canvas)


@iiif.route('/iiif/<path:manif_id>/annotation/<anno_id>.json')
@iiif.route('/iiif/<path:manif_id>/annotation/<anno_id>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_image_annotation(manif_id, anno_id):
    """ Obtain the given image annotation from a manifest. """
    anno = Manifest.get_image_annotation(manif_id, anno_id)
    if anno is None:
        abort(404)
    else:
        return jsonify(anno)


@iiif.route('/iiif/<path:manif_id>/range/<range_id>.json')
@iiif.route('/iiif/<path:manif_id>/range/<range_id>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_range(manif_id, range_id):
    """ Obtain the given range from a manifest. """
    range_ = Manifest.get_range(manif_id, range_id)
    if range_ is None:
        abort(404)
    else:
        return jsonify(range_)


@iiif.route('/iiif/image/<image_id>/info.json')
@auto.doc(groups=['iiif'])
@cors('*')
def get_image_info(image_id):
    """ Obtain the info.json for the given image. """
    img = IIIFImage.get(image_id)
    if img is None:
        abort(404)
    else:
        return jsonify(img.info)


@iiif.route(
    '/iiif/image/<image_id>/<region>/<size>/<rotation>/<quality>.<format>')
@auto.doc(groups=['iiif'])
@cors('*')
def get_image(image_id, region, size, rotation, quality, format):
    """ Obtain a redirect to the image resource for the given IIIF Image API
        request. """
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
        return redirect(url, 301)


@iiif.route('/iiif/annotation/<annotation_id>', methods=['GET'])
@auto.doc(groups=['iiif'])
@cors('*')
def get_annotation(annotation_id):
    anno = Annotation.get(annotation_id)
    if anno is None:
        abort(404)
    else:
        return jsonify(anno.annotation)


@iiif.route('/iiif/annotation/<annotation_id>', methods=['DELETE'])
@auto.doc(groups=['iiif'])
@cors('*')
def delete_annotation(annotation_id):
    anno = Annotation.get(annotation_id)
    if anno is None:
        abort(404)
    else:
        Annotation.delete(anno)
        db.session.commit()
        return jsonify(anno.annotation)


@iiif.route('/iiif/annotation/<annotation_id>', methods=['PUT'])
@auto.doc(groups=['iiif'])
@cors('*')
def update_annotation(annotation_id):
    anno = Annotation.get(annotation_id)
    if anno is None:
        abort(404)
    if request.json['@id'].split('/')[-1] != anno.id:
        abort(400)
    anno = Annotation(request.json)
    Annotation.save(anno)
    db.session.commit()
    return jsonify(anno.annotation)


@iiif.route('/iiif/annotation', methods=['GET'])
@auto.doc(groups=['iiif'])
@cors('*')
def search_annotations():
    search_args = {}
    if 'motivation' in request.args:
        search_args['motivation'] = request.args['motivation']
    if 'q' in request.args:
        search_args['target'] = request.args['q']
    if 'date' in request.args:
        search_args['date_ranges'] = [
            r.split('/') for r in request.args['date'].split(' ')]
    base_url = "{}://{}".format(
        current_app.config['PREFERRED_URL_SCHEME'],
        current_app.config['SERVER_NAME'])
    page_num = int(request.args.get('p', '1'))
    limit = int(request.args.get('limit', '100'))
    pagination = Annotation.search(**search_args).paginate(
        page=page_num, per_page=limit, error_out=False)
    return jsonify(make_annotation_list(
        pagination, request.url, request.args, base_url))


@iiif.route('/iiif/annotation', methods=['POST'])
@auto.doc(groups=['iiif'])
@cors('*')
def create_annotation():
    anno_data = request.json
    anno_data['@id'] = url_for('iiif.get_annotation', _external=True,
                               annotation_id=shortuuid.uuid())
    anno = Annotation(anno_data)
    Annotation.save(anno)
    db.session.commit()
    return jsonify(anno.annotation)
