import re

from flask import Blueprint, abort, current_app, render_template
from jinja2 import Markup, escape, evalcontextfilter

from ..models import Manifest
from ..extensions import auto


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
    from .iiif import get_collection
    return render_template(
        'browse.html',
        root_collection=get_collection('index', 'top').get_data(True),
        initial_page=get_collection('index', 'p1').get_data(True))


@view.route('/about')
def about():
    return render_template('about.html')


@view.route('/apidocs')
def apidocs():
    return render_template('apidocs.html', api=auto.generate('api'),
                           iiif=auto.generate('iiif'))
