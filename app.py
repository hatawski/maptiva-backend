from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta, timezone
import qrcode
import os
import pandas as pd
from pathlib import Path
import uuid
from threading import Lock
from flask_socketio import SocketIO, emit, join_room

PHT = timezone(timedelta(hours=8))

def now_pht():
    return datetime.now(PHT).replace(tzinfo=None)

app = Flask(__name__, static_folder="static")

ALLOWED_ORIGINS = [
    "http://50.0.14.185:3000",
    "https://alejandra-uncognisable-undescriptively.ngrok-free.dev",
    "https://maptiva.loca.lt",
    "*"
    
]

CORS(app,
     resources={r"/*": {"origins": ALLOWED_ORIGINS}},
     supports_credentials=True)

socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode="threading",
    allow_upgrades=False
)



@socketio.on("join_pc")
def handle_pc_join(data):
    pc_name = data.get("pc_name")
    join_room(f"pc_{pc_name}")
    print(f"PC joined room: pc_{pc_name}")

@socketio.on("join_mobile")
def handle_mobile_join(data):
    student_id = data.get("student_id")
    join_room(f"mobile_{student_id}")
    print(f"Mobile joined room: mobile_{student_id}")

@socketio.on("join_student")
def handle_student_join(data):
    student_id = data.get("student_id")
    join_room(f"student_{student_id}")
    print(f"Student joined room: student_{student_id}")

@socketio.on("join")
def handle_join(data):
    token = data.get("token")
    if not token:
        return
    join_room(token)
    print(f"✅ Web client joined room: {token}")


# === DATABASE CONFIGURATION ===
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///database.db'
).replace("postgres://", "postgresql://")  # ← Render uses old format
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === MODELS ===
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    student_id = db.Column(db.String(20), unique=True)
    password = db.Column(db.String(120))
    qr_code = db.Column(db.String(120), nullable=True)

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(120))

class PC(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pc_name = db.Column(db.String(50), unique=True)
    status = db.Column(db.String(50), default="available")
    assigned_to = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    pc_id = db.Column(db.Integer, db.ForeignKey('pc.id'))
    checked_in_at = db.Column(db.DateTime)
    checked_out_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default="reserved")

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)  # ✅ nullable
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_pht)

class PermissionRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    pc_id = db.Column(db.Integer, db.ForeignKey('pc.id'))
    status = db.Column(db.String(50), default="pending")
    requested_at = db.Column(db.DateTime, default=now_pht)

# === CLEANUP STALE SESSIONS ===
def cleanup_stale_sessions():
    occupied_pcs = PC.query.filter_by(status="occupied").all()
    for pc in occupied_pcs:
        reservation = Reservation.query.filter_by(
            pc_id=pc.id,
            status="confirmed"
        ).first()
        if reservation:
            reservation.status = "force_checked_out"
            reservation.checked_out_at = now_pht()
        pc.status = "available"
        pc.assigned_to = None
        print(f"🔄 Cleaned up stale session: {pc.pc_name}")
    db.session.commit()

# === INITIALIZATION ===
with app.app_context():
    db.create_all()
    cleanup_stale_sessions()  # ✅ clean up on restart
    if not Admin.query.filter_by(username="admin").first():
        admin = Admin(username="admin", password="1234")
        db.session.add(admin)
    if PC.query.count() == 0:
        for i in range(1, 31):
            pc = PC(pc_name=f"PC{i:02d}")
            db.session.add(pc)
    db.session.commit()

# === CLEANUP FUNCTIONS ===
def cleanup_old_qr_codes():
    folder = "static/qr_codes"
    if not os.path.exists(folder):
        return
    now = datetime.utcnow()
    for filename in os.listdir(folder):
        file_path = os.path.join(folder, filename)
        if os.path.isfile(file_path):
            modified_time = datetime.utcfromtimestamp(os.path.getmtime(file_path))
            if (now - modified_time).days >= 2:
                try:
                    os.remove(file_path)
                    print(f"🧹 Deleted old QR: {filename}")
                except Exception as e:
                    print(f"⚠️ Error deleting {filename}: {e}")

def cleanup_old_attendance():
    ten_days_ago = now_pht() - timedelta(days=7)
    old_records = Reservation.query.filter(Reservation.checked_in_at < ten_days_ago).all()
    for record in old_records:
        db.session.delete(record)
    db.session.commit()

# === ROUTES ===

@app.after_request
def after_request(response):
    origin = request.headers.get("Origin")
    # Dynamically allow the origin if it matches our ngrok domain
    if origin and ("ngrok-free.dev" in origin or "50.0.14.185" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
        
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, ngrok-skip-browser-warning, Bypass-Tunnel-Reminder"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response


@app.route("/debug/pcs")
def debug_pcs():
    pcs = PC.query.all()
    return jsonify([pc.pc_name for pc in pcs])

# === STUDENT SIGNUP ===
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    existing_student = Student.query.filter_by(student_id=data["student_id"]).first()
    if existing_student:
        return jsonify({"message": "Student ID already exists"}), 400

    student = Student(
        name=data["name"],
        student_id=data["student_id"],
        password=data["password"]
    )
    db.session.add(student)
    db.session.commit()

    qr_data = f"{student.id}-{student.student_id}"
    qr_folder = "static/qr_codes"
    os.makedirs(qr_folder, exist_ok=True)
    qr_path = os.path.join(qr_folder, f"qr_{student.id}.png")
    qr_img = qrcode.make(qr_data)
    qr_img.save(qr_path)
    student.qr_code = qr_path
    db.session.commit()

    return jsonify({
        "message": "Account created successfully",
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "qr_code": student.qr_code
    }), 201

# === STUDENT LOGIN ===
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    student = Student.query.filter_by(
        student_id=data["student_id"],
        password=data["password"]
    ).first()

    if not student:
        return jsonify({"message": "Invalid credentials"}), 401

    qr_data = f"{student.id}-{student.student_id}-{now_pht().timestamp()}"
    qr_folder = "static/qr_codes"
    os.makedirs(qr_folder, exist_ok=True)
    qr_path = os.path.join(qr_folder, f"login_qr_{student.id}.png")
    qr_img = qrcode.make(qr_data)
    qr_img.save(qr_path)
    student.qr_code = qr_path
    db.session.commit()

    return jsonify({
        "message": "Login successful",
        "id": student.id,
        "student_id": student.student_id,
        "name": student.name,
        "qr_code": student.qr_code
    }), 200

# === RESERVE PC ===
@app.route("/reserve", methods=["POST"])
def reserve_pc():
    cleanup_old_attendance()
    data = request.json
    student_id = data["student_id"]
    pc_name = data["pc_name"]

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"message": "Invalid PC name"}), 404
    if pc.status != "available":
        return jsonify({"message": "PC already reserved"}), 400

    pc.status = "occupied"
    pc.assigned_to = student_id
    reservation = Reservation(
        student_id=student_id,
        pc_id=pc.id,
        checked_in_at=now_pht(),
        status="confirmed"
    )
    db.session.add(reservation)
    db.session.commit()

    socketio.emit("pc_unlocked", {"pc_name": pc_name}, room=f"student_{student_id}")

    return jsonify({
        "message": f"{pc_name} reserved successfully",
        "pc_name": pc_name,
        "checked_in_at": now_pht().strftime("%I:%M %p")
    }), 200

# === STUDENT RESERVATION CHECK ===
@app.route("/student/reservation/<int:student_id>", methods=["GET"])
def get_student_reservation(student_id):
    pc = PC.query.filter_by(assigned_to=student_id).first()
    if not pc:
        return jsonify({"message": "No active reservation"}), 404
    reservation = Reservation.query.filter_by(pc_id=pc.id, status="confirmed").first()
    return jsonify({
        "pc_name": pc.pc_name,
        "checked_in_at": reservation.checked_in_at.strftime("%I:%M %p") if reservation else ""
    }), 200

# === CHECKOUT ===
@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json
    student_id = data["student_id"]
    pc = PC.query.filter_by(assigned_to=student_id).first()
    if not pc:
        return jsonify({"message": "No active reservation found"}), 404

    reservation = Reservation.query.filter_by(pc_id=pc.id, status="confirmed").first()
    if reservation:
        reservation.status = "checked_out"
        reservation.checked_out_at = now_pht()
        db.session.commit()

    pc.status = "available"
    pc.assigned_to = None
    db.session.commit()

    socketio.emit("pc_locked", {}, room=f"student_{student_id}")
    socketio.emit("pc_locked", {}, room=f"mobile_{student_id}")

    return jsonify({"message": "Checked out successfully"}), 200

# === REPORT ISSUE ===
@app.route("/report", methods=["POST"])
def report_issue():
    data = request.json
    student_id = data.get("student_id")
    message = data.get("message")

    if not message:
        return jsonify({"message": "Message is required"}), 400

    # ✅ Handle string, integer, or null student_id
    if student_id is None:
        report = Report(student_id=None, message=message)
    elif isinstance(student_id, str):
        student = Student.query.filter_by(student_id=student_id).first()
        report = Report(
            student_id=student.id if student else None,
            message=message
        )
    else:
        report = Report(student_id=student_id, message=message)

    db.session.add(report)
    db.session.commit()
    return jsonify({"message": "Report sent successfully"}), 201

# === PERMISSION REQUEST ===
@app.route("/request-permission", methods=["POST"])
def request_permission():
    data = request.json
    student_id = data.get("student_id")
    pc_name = data.get("pc_name")

    if not student_id or not pc_name:
        return jsonify({"message": "Missing student_id or pc_name"}), 400

    if isinstance(student_id, str):
        student = Student.query.filter_by(student_id=student_id).first()
        if not student:
            return jsonify({"message": "Student not found"}), 404
        student_id = student.id

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"message": "Invalid PC name"}), 404

    request_entry = PermissionRequest(student_id=student_id, pc_id=pc.id)
    db.session.add(request_entry)
    db.session.commit()
    return jsonify({"message": "Permission request sent to admin"}), 200

# === ADMIN LOGIN ===
@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    admin = Admin.query.filter_by(
        username=data["username"],
        password=data["password"]
    ).first()
    if not admin:
        return jsonify({"message": "Invalid admin credentials"}), 401
    return jsonify({"message": "Admin login successful"}), 200

# === ADMIN VIEW PCS ===
@app.route("/admin/pcs", methods=["GET"])
def admin_view_pcs():
    pcs = PC.query.order_by(PC.pc_name.asc()).all()
    data = []
    for pc in pcs:
        student = None
        if pc.assigned_to:
            s = Student.query.get(pc.assigned_to)
            student = {"name": s.name, "student_id": s.student_id}
        data.append({
            "id": pc.id,
            "pc_name": pc.pc_name,
            "status": pc.status,
            "student": student
        })
    return jsonify(data), 200

# === ADMIN VIEW REPORTS ===
@app.route("/admin/reports", methods=["GET"])
def admin_view_reports():
    reports = Report.query.order_by(Report.created_at.desc()).all()
    data = []
    for r in reports:
        student = Student.query.get(r.student_id) if r.student_id else None
        data.append({
            "id": r.id,
            "student_name": student.name if student else "Anonymous",
            "message": r.message,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })
    return jsonify(data), 200

# === ADMIN VIEW PERMISSION REQUESTS ===
@app.route("/admin/requests", methods=["GET"])
def admin_view_requests():
    requests = PermissionRequest.query.order_by(
        PermissionRequest.requested_at.desc()
    ).all()
    data = []
    for r in requests:
        student = Student.query.get(r.student_id)
        pc = PC.query.get(r.pc_id)
        data.append({
            "id": r.id,
            "student_name": student.name if student else "Unknown",
            "pc_name": pc.pc_name if pc else "Unknown",
            "status": r.status
        })
    return jsonify(data), 200

# === ADMIN HANDLE PERMISSION ===
@app.route("/admin/handle-request", methods=["POST"])
def handle_permission():
    data = request.json
    req = PermissionRequest.query.get(data["request_id"])
    if not req:
        return jsonify({"message": "Request not found"}), 404

    req.status = data["action"]
    db.session.commit()

    if data["action"] == "accepted":
        pc = PC.query.get(req.pc_id)

        if pc and pc.status == "available":
            pc.status = "occupied"
            pc.assigned_to = req.student_id
            reservation = Reservation(
                student_id=req.student_id,
                pc_id=pc.id,
                checked_in_at=now_pht(),
                status="confirmed"
            )
            db.session.add(reservation)
            db.session.commit()

        socketio.emit(
            "pc_unlocked",
            {
                "pc_name": pc.pc_name,
                "checked_in_at": now_pht().strftime("%I:%M %p")
            },
            room=f"student_{req.student_id}"
        )

        socketio.emit(
            "pc_unlocked_mobile",
            {
                "pc_name": pc.pc_name,
                "checked_in_at": now_pht().strftime("%I:%M %p")
            },
            room=f"mobile_{req.student_id}"
        )

    return jsonify({"message": f"Request {data['action']}"}), 200

# === ADMIN FORCE CHECKOUT ===
@app.route("/admin/force-checkout", methods=["POST"])
def admin_force_checkout():
    data = request.json
    pc_name = data.get("pc_name")

    pc = PC.query.filter_by(pc_name=pc_name).first()
    if not pc:
        return jsonify({"message": "PC not found"}), 404

    if pc.status == "available":
        return jsonify({"message": "PC is already available"}), 400

    student_id = pc.assigned_to  # ✅ save before clearing

    reservation = Reservation.query.filter_by(
        pc_id=pc.id, status="confirmed"
    ).first()
    if reservation:
        reservation.status = "force_checked_out"
        reservation.checked_out_at = now_pht()

    pc.status = "available"
    pc.assigned_to = None
    db.session.commit()

    # ✅ Notify both web and mobile
    if student_id:
        socketio.emit("pc_locked", {}, room=f"student_{student_id}")
        socketio.emit("pc_locked", {}, room=f"mobile_{student_id}")

    return jsonify({
        "message": f"{pc_name} has been forcefully checked out by admin."
    }), 200

# === ADMIN ATTENDANCE ===
@app.route("/admin/attendance", methods=["GET"])
def get_attendance():
    reservations = Reservation.query.order_by(
        Reservation.checked_in_at.desc()
    ).all()
    data = []
    for r in reservations:
        student = Student.query.get(r.student_id)
        pc = PC.query.get(r.pc_id)
        data.append({
            "name": student.name if student else "Unknown",
            "student_id": student.student_id if student else "Unknown",
            "pc_name": pc.pc_name if pc else "Unknown",
            "time_in": r.checked_in_at.strftime("%Y-%m-%d %I:%M %p") if r.checked_in_at else "",
            "time_out": r.checked_out_at.strftime("%Y-%m-%d %I:%M %p") if r.checked_out_at else "Still in",
            "status": r.status
        })
    return jsonify(data), 200

# === EXPORT ATTENDANCE ===
@app.route("/admin/export-attendance", methods=["GET"])
def export_attendance():
    documents_path = Path.home() / "Documents" / "Attendance_Logs"
    documents_path.mkdir(parents=True, exist_ok=True)

    reservations = Reservation.query.all()
    data = []
    for r in reservations:
        student = Student.query.get(r.student_id)
        pc = PC.query.get(r.pc_id)
        data.append({
            "Name": student.name if student else "Unknown",
            "Student ID": student.student_id if student else "Unknown",
            "PC Name": pc.pc_name if pc else "Unknown",
            "Time In": r.checked_in_at.strftime("%Y-%m-%d %H:%M:%S") if r.checked_in_at else "",
            "Time Out": r.checked_out_at.strftime("%Y-%m-%d %H:%M:%S") if r.checked_out_at else "",
            "Status": r.status
        })

    if not data:
        return jsonify({"message": "No attendance records to export"}), 404

    df = pd.DataFrame(data)
    filename = f"attendance_log_{now_pht().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
    filepath = documents_path / filename
    df.to_excel(filepath, index=False)

    return jsonify({
        "message": "Attendance log exported successfully",
        "file_path": str(filepath)
    }), 200

# === QR TOKEN MANAGEMENT ===
active_qr_tokens = {}
token_lock = Lock()

@app.route("/qr-token", methods=["GET"])
def qr_token():
    token = str(uuid.uuid4())
    expires_at = now_pht() + timedelta(minutes=2)
    with token_lock:
        active_qr_tokens[token] = {"expires_at": expires_at}
    return jsonify({
        "token": token,
        "expires_at": expires_at.isoformat()
    }), 200

@app.route("/qr-login", methods=["POST"])
def qr_login():
    data = request.json
    token = data.get("token")
    student_id = data.get("student_id")

    if not token or not student_id:
        return jsonify({"message": "Missing token or student_id"}), 400

    with token_lock:
        token_data = active_qr_tokens.get(token)
        if not token_data:
            return jsonify({"message": "Invalid or expired token"}), 404
        if now_pht() > token_data["expires_at"]:
            del active_qr_tokens[token]
            return jsonify({"message": "Token expired"}), 410

    student = Student.query.filter_by(student_id=student_id).first()
    if not student:
        return jsonify({"message": "Student not found"}), 404

    socketio.emit(
        "qr_authorized",
        {
            "id": student.id,
            "student_id": student.student_id,
            "name": student.name
        },
        room=token
    )

    with token_lock:
        if token in active_qr_tokens:
            del active_qr_tokens[token]

    return jsonify({"message": "QR login successful"}), 200

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )