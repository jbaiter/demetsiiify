import json
import re
import traceback
from urllib.parse import unquote

import requests
from flask import (Blueprint, abort, current_app, jsonify, redirect, request,
                   url_for)
from rq import Connection, get_failed_queue
from validate_email import validate_email

from .. import mets
from ..extensions import auto
from ..models import Identifier, Manifest
from ..tasks import queue, get_redis, import_mets_job

api = Blueprint('api', __name__)


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


@api.errorhandler(Exception)
def handle_error(error):
    return jsonify({
        'traceback': traceback.format_exc()
    }), 500


@api.route('/api/recent')
@auto.doc(groups=['api'])
def api_get_recent_manifests():
    """ Get list of recently imported manifests.

    Takes a single request parameter `page_num` to specify the page to
    obtain.
    """
    page_num = int(request.args.get('page', '1'))
    if page_num < 1:
        page_num = 1
    query = Manifest.query.order_by(Manifest.surrogate_id.desc())
    pagination = query.paginate(
        page=page_num, error_out=False,
        per_page=current_app.config['ITEMS_PER_PAGE'])
    return jsonify(dict(
        next_page=pagination.next_num if pagination.has_next else None,
        manifests=[
            {'@id': url_for('iiif.get_manifest', manif_id=m.id,
                            _external=True),
             'thumbnail': m.manifest.get(
                 'thumbnail',
                 m.manifest['sequences'][0]['canvases'][0]['thumbnail']),
             'label': m.label,
             'metsurl': m.origin,
             'attribution': m.manifest['attribution'],
             'attribution_logo': m.manifest['logo']}
            for m in pagination.items]))


@api.route('/api/resolve/<identifier>')
@auto.doc(groups=['api'])
def api_resolve(identifier):
    """ Resolve identifier to IIIF manifest.

    Redirects to the corresponding manifest if resolving was successful,
    otherwise returns 404.
    """
    manifest_id = Identifier.resolve(identifier)
    if manifest_id is None:
        abort(404)
    else:
        return redirect(url_for('iiif.get_manifest', manif_id=manifest_id))


def _extract_mets_from_dfgviewer(url):
    url = unquote(url)
    mets_url = re.findall(r'set\[mets\]=(http[^&]+)', url)
    if not mets_url:
        mets_url = re.findall(r'tx_dlf\[id\]=(http.+)', url)
    if mets_url:
        return mets_url[0]
    else:
        return None


@api.route('/api/import', methods=['POST'])
@auto.doc(groups=['api'])
def api_import():
    """ Start the import process for a METS document.

    The request payload must be a JSON object with a single `url` key that
    contains the URL of the METS document to be imported.

    Instead of a METS URL, you can also specify the URL of a DFG-Viewer
    instance.

    Will return the job status as a JSON document.
    """
    mets_url = request.json.get('url')
    if re.match(r'https?://dfg-viewer.de/.*?', mets_url):
        mets_url = _extract_mets_from_dfgviewer(mets_url)
    resp = None
    try:
        resp = requests.head(mets_url, timeout=30)
    except:
        pass
    if not resp:
        return jsonify({
            'message': 'There is no METS available at the given URL.'}), 400
    job_meta = mets.get_basic_info(mets_url)
    job = queue.enqueue(import_mets_job, mets_url, meta=job_meta)
    job.refresh()
    status_url = url_for('api.api_task_status', task_id=job.id,
                         _external=True)
    response = jsonify(_get_job_status(job.id))
    response.status_code = 202
    response.headers['Location'] = status_url
    return response


def _get_job_status(job):
    if isinstance(job, str):
        job = queue.fetch_job(job)
        if job is None:
            with Connection(get_redis()):
                failed_queue = get_failed_queue()
            job = failed_queue.fetch_job(job)
        if job is None:
            return None
    status = job.get_status()
    out = {'id': job.id,
           'status': status}
    if status != 'failed':
        out.update(job.meta)
    if status == 'failed':
        out['traceback'] = job.exc_info
    elif status == 'queued':
        job_ids = queue.get_job_ids()
        out['position'] = job_ids.index(job.id) if job.id in job_ids else None
    elif status == 'finished':
        out['result'] = job.result
    return out


@api.route('/api/tasks', methods=['GET'])
@auto.doc(groups=['api'])
def api_list_tasks():
    """ List currently enqueued import jobs.

    Does not list currently executing jobs!
    """
    return jsonify(
        {'tasks': [_get_job_status(job_id) for job_id in queue.job_ids]})


@api.route('/api/tasks/<task_id>', methods=['GET'])
@auto.doc(groups=['api'])
def api_task_status(task_id):
    """ Obtain status for a single job. """
    status = _get_job_status(task_id)
    if status:
        return jsonify(status)
    else:
        abort(404)


@api.route('/api/tasks/<task_id>/stream')
@auto.doc(groups=['api'])
def sse_stream(task_id):
    """ Obtain a Server-Sent Event (SSE) stream for a given job.

    The stream will deliver all updates to the status.
    """
    redis = get_redis()
    job = queue.fetch_job(task_id)
    if job is None:
        with Connection(redis):
            failed_queue = get_failed_queue()
        job = failed_queue.fetch_job(task_id)
    if job is None:
        abort(404)

    def gen(redis):
        # NOTE: This is wasteful, yes, but in order to get updates when
        #  the queue position changes, we have to check at every update of
        #  every other job
        channel_name = '__keyspace@0__:rq:job:*'
        pubsub = redis.pubsub()
        pubsub.psubscribe(channel_name)
        last_status = None
        last_id = None

        for msg in pubsub.listen():
            # To learn about queue position changes, watch for changes
            # in the currently active
            cur_id = msg['channel'].decode('utf8').split(':')[-1]
            skip = (cur_id == last_id and
                    last_status and last_status['status'] != 'started')
            if skip:
                continue
            last_id = cur_id
            status = _get_job_status(task_id)
            if status == last_status:
                continue
            yield ServerSentEvent(status).encode()
            last_status = status
    resp = current_app.response_class(gen(redis), mimetype="text/event-stream")
    resp.headers['X-Accel-Buffering'] = 'no'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


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
