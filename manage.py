from flask import current_app
from flask_script import Shell, Manager, Server, prompt_bool

from demetsiiify import db, create_app


def _make_context():
    return dict(
        app=current_app,
        drop=drop,
        create=create,
        recreate=recreate)


app = create_app()
manager = Manager(app)
manager.add_command('runserver', Server(host='0.0.0.0', port=5000))
manager.add_command('shell', Shell(make_context=lambda: _make_context()))


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
