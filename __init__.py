from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime

db = SQLAlchemy()

# ==========================================
# 📊 MAPTIVA SQLITE DATABASE SCHEMAS
# ==========================================
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)

class PC(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pc_name = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default="available") # available / occupied

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(50), nullable=False)
    pc_name = db.Column(db.String(50), nullable=False)
    time_in = db.Column(db.String(50), nullable=False)
    time_out = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default="active") # active / completed

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        # Create a default admin account if it's a completely new database
        if not Admin.query.filter_by(username="admin").first():
            admin = Admin(username="admin", password="1234")
            db.session.add(admin)
            db.session.commit()

    return app