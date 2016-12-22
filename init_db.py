import logging

from demetsiiify.web import app
from demetsiiify.models import db

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    with app.app_context():
        print("Dropping previous tables")
        db.drop_all()
        print("Creating tables")
        db.create_all()
