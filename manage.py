from flask import current_app
from flask_script import Shell, Manager, prompt_bool
from flask_migrate import Migrate, MigrateCommand

from demetsiiify import db, create_app, make_worker, make_redis


def _make_context():
    return dict(
        app=current_app,
        worker=worker,
        drop=drop,
        create=create,
        recreate=recreate)


app = create_app()
migrate = Migrate(app, db)
manager = Manager(app)
manager.add_command('shell', Shell(make_context=lambda: _make_context()))
manager.add_command('db', MigrateCommand)


@manager.command
def worker():
    redis = make_redis()
    worker = make_worker(redis)
    worker.work()


@manager.command
def drop():
    """Drops database tables"""
    if prompt_bool('Are you sure you want to lose all your data?'):
        db.drop_all()


@manager.command
def create():
    """Creates database tables from sqlalchemy models"""
    db.create_all()


@manager.command
def recreate(default_data=True, sample_data=False):
    """Recreates database tables (same as issuing 'drop' and then 'create')"""
    drop()
    create()


if __name__ == '__main__':
    manager.run()
