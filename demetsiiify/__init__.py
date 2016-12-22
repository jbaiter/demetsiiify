import os

from celery import Celery
from flask import Flask, current_app

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
    app = Flask(__name__)
    app.config['PREFERRED_URL_SCHEME'] = os.environ.get(
        'PREFERRED_URL_SCHEME', 'http')
    app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:5000')
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', DEFAULT_SECRET)
    app.config['CELERY_BROKER_URL'] = 'redis://redis:6379/0'
    app.config['CELERY_RESULT_BACKEND'] = 'redis://redis:6379/0'
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        'postgresql://postgres:postgres@postgres:5432/postgres')
    db.init_app(app)
    app.before_request(_force_preferred_scheme)
    with app.app_context():
        from .blueprints import view, api, iiif
    app.register_blueprint(view)
    app.register_blueprint(api)
    app.register_blueprint(iiif)
    return app


def make_celery(app=None):
    app = app or create_app()
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
