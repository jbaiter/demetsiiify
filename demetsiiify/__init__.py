import os

from flask import Flask, current_app
from redis import Redis
from rq import Connection, Queue, Worker, get_failed_queue

from .extensions import db


DEFAULT_SECRET = """
larencontrefortuitesurunetablededissectiond'unemachineàcoudreetd'unparapluie
"""


def _force_preferred_scheme():
    if current_app.config['PREFERRED_URL_SCHEME'] == 'https':
        from flask import _request_ctx_stack
        if _request_ctx_stack is not None:
            reqctx = _request_ctx_stack.top
            reqctx.url_adapter.url_scheme = 'https'


def create_app():
    app = Flask(__name__, template_folder='../templates',
                static_folder='../static')
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get(
        'PREFERRED_URL_SCHEME', 'http')
    app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:5000')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', DEFAULT_SECRET)
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'postgresql://postgres:postgres@postgres:5432/postgres')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    app.before_request(_force_preferred_scheme)
    with app.app_context():
        from .blueprints import view, api, iiif
    app.register_blueprint(view)
    app.register_blueprint(api)
    app.register_blueprint(iiif)
    return app


def make_redis():
    redis = Redis.from_url('redis://redis:6379/0')
    # For our SSE endoint, we want to be notified of all changes to hashmaps
    # with a given key (i.e. when a job is updated)
    redis.config_set('notify-keyspace-events', 'Kh')
    return redis


def make_queues(redis):
    with Connection(redis):
        return (Queue('tasks', default_timeout=60*60),
                get_failed_queue())


def _exception_handler(job, exc_type, exc_value, traceback):
    try:
        typename = ".".join((exc_value.__module__,
                             exc_value.__class__.__name__))
    except AttributeError:
        typename = exc_value.__class__.__name__
    job.meta = {
        'type': typename,
        'message': exc_value.args[0]}
    job.save()


def make_worker(redis):
    with Connection(redis):
        queues = [Queue('tasks', default_timeout=60*60)]
        worker = Worker(queues)
        worker.push_exc_handler(_exception_handler)
        return worker
