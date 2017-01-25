import re

from flask import Blueprint, abort, current_app, render_template
from jinja2 import Markup, escape, evalcontextfilter

from ..models import Manifest, Annotation, Collection
from ..extensions import auto
from ..iiif import make_manifest_collection, make_annotation_list


PARAGRAPH_RE = re.compile(r'(?:\r\n|\r|\n){2,}')


view = Blueprint('view', __name__)


@view.app_template_filter()
@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p
                          for p in PARAGRAPH_RE.split(escape(value)))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


@view.context_processor
def inject_debug():
    return dict(debug=current_app.debug)


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
    return render_template('index.html')


@view.route('/recent')
def recent():
    return render_template('recent.html')


@view.route('/browse')
def browse():
    pagination = Manifest.query.paginate(
        page=1, per_page=current_app.config['ITEMS_PER_PAGE'])
    subcollections = (
        Collection.query.filter_by(parent_collection=None).all())
    label = "All manifests available at {}".format(
        current_app.config['SERVER_NAME'])
    return render_template(
        'browse.html',
        root_collection=make_manifest_collection(
            pagination, subcollections, label, 'index', 'top'),
        initial_page=make_manifest_collection(
            pagination, subcollections, label, 'index', 'p1'))


@view.route('/about')
def about():
    return render_template('about.html')


@view.route('/apidocs')
def apidocs():
    return render_template('apidocs.html', api=auto.generate('api'),
                           iiif=auto.generate('iiif'))
