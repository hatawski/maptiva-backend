from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    from ..Frontend.src.pages.models import Student, Admin, PC, Reservation

    with app.app_context():
        db.create_all()
        # Create a default admin if not exists
        if not Admin.query.filter_by(username="admin").first():
            admin = Admin(username="admin", password="1234")
            db.session.add(admin)
            db.session.commit()

    return app
