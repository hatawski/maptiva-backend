from flask import Flask, request, jsonify, send_file, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_mail import Mail, Message 
from datetime import datetime, timedelta, timezone
import qrcode
import os
import io
import shutil  # ◄ Added for automated file-level database backups
import pandas as pd
from pathlib import Path
import uuid
import random 
from threading import Lock
from flask_socketio import SocketIO, emit, join_room

PHT = timezone(timedelta(hours=8))

def now_pht():
    return datetime.now(PHT).replace(tzinfo=None)

app = Flask(__name__, static_folder="static")

ALLOWED_ORIGINS = [
    "http://50.0.14.185:3000",
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

# === 📑 FLASK-MAIL CONFIGURATION FOR GMAIL ===
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'ruizoldean@gmail.com'  # ◄ Replace this
app.config['MAIL_PASSWORD'] = 'dfop avqi baba rizq'  # ◄ Replace with 16-char App Password
app.config['MAIL_DEFAULT_SENDER'] = ('Maptiva Support', 'ruizoldean@gmail.com')

mail = Mail(app)

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
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    f'sqlite:///{os.path.join(BASE_DIR, "database.db")}' # ◄ Forces it into /opt/maptiva-backend/database.db
).replace("postgres://", "postgresql://")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# === MODELS ===
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    student_id = db.Column(db.String(20), unique=True)
    password = db.Column(db.String(120))
    qr_code = db.Column(db.String(120), nullable=True)
    # ✅ Added recovery layout rows
    email = db.Column(db.String(120), unique=True, nullable=True) 
    reset_otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)

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

# === 🛡️ DATABASE BACKUP CORE SYSTEM ===
def execute_database_backup():
    """Generates a timestamped, redundant file-level snapshot of the SQLite database layer"""
    try:
        # Extract the path from the SQLite URI string format
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        if "sqlite:///" in db_uri:
            source_db = db_uri.replace("sqlite:///", "")
        else:
            source_db = os.path.join(BASE_DIR, "database.db")

        backup_dir = os.path.join(BASE_DIR, "backups")
        
        # Build backup infrastructure folder if omitted
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
            
        if os.path.exists(source_db):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            backup_filename = f"backup_{timestamp}.db"
            destination = os.path.join(backup_dir, backup_filename)
            
            # Execute snapshot cloning routine
            shutil.copy2(source_db, destination)
            print("\n" + "="*52)
            print(f"🛡️  DATABASE COMPLIANCE BACKUP CREATED:\n    📍 {destination}")
            print("="*52 + "\n")
        else:
            print(f"⚠️  Backup deferred: Source '{source_db}' is not built yet.")
    except Exception as e:
        print(f"❌ Critical Error during database transaction backup: {e}")

# === INITIALIZATION ===
with app.app_context():
    # 1. Execute redundancy snapshot before mutating any structural schemas
    execute_database_backup()
    
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
    if origin and ("trycloudflare.com" in origin or "ngrok-free.dev" in origin or "50.0.14.185" in origin):
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
       
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
    
    if not data.get("email") or "@" not in data.get("email"):
        return jsonify({"message": "Valid email address is required"}), 400

    existing_student = Student.query.filter_by(student_id=data["student_id"]).first()
    if existing_student:
        return jsonify({"message": "Student ID already exists"}), 400

    existing_email = Student.query.filter_by(email=data["email"]).first()
    if existing_email:
        return jsonify({"message": "Email is already registered"}), 400

    student = Student(
        name=data["name"],
        student_id=data["student_id"],
        password=data["password"],
        email=data["email"] # ✅ Capture input email field
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
        "email": student.email,
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

# === 📑 FORGOT PASSWORD (REQUEST CODE) ===
@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"message": "Email field is required"}), 400

    student = Student.query.filter_by(email=email).first()
    if not student:
        # Prevent layout disclosure enumeration, tell user sent if match exists
        return jsonify({"message": "If account exists, validation code has been sent."}), 200

    # Generate distinct 6-character recovery PIN
    otp = f"{random.randint(100000, 999999)}"
    student.reset_otp = otp
    student.otp_expiry = now_pht() + timedelta(minutes=10) # 10 minute window bounds
    db.session.commit()

    try:
        msg = Message("Maptiva Account Recovery Code", recipients=[email])
        msg.body = f"Hello {student.name},\n\nYou requested to reset your password. Use the verification token code below to update your login credentials:\n\n{otp}\n\nThis code expires in 10 minutes."
        mail.send(msg)
        return jsonify({"message": "Verification token sent successfully."}), 200
    except Exception as e:
        print(f"SMTP Transmission failure: {e}")
        return jsonify({"message": "Failed to send email. Server configuration error."}), 500

# === 📑 RESET PASSWORD (CONFIRM CODE) ===
@app.route("/auth/reset-password", methods=["POST"])
def reset_password():
    data = request.json
    email = data.get("email")
    otp = data.get("otp")
    new_password = data.get("new_password")

    if not email or not otp or not new_password:
        return jsonify({"message": "Missing validation requirements"}), 400

    student = Student.query.filter_by(email=email).first()
    if not student or student.reset_otp != otp:
        return jsonify({"message": "Incorrect or invalid verification code"}), 400

    if now_pht() > student.otp_expiry:
        return jsonify({"message": "Recovery token expired. Request a new code."}), 400

    # Clear active OTP token states out to prevent structural replay exploits
    student.password = new_password  # Storing as text to match your existing login approach
    student.reset_otp = None
    student.otp_expiry = None
    db.session.commit()

    return jsonify({"message": "Password updated successfully. Proceed to Login."}), 200

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

    student_id = pc.assigned_to

    reservation = Reservation.query.filter_by(
        pc_id=pc.id, status="confirmed"
    ).first()
    if reservation:
        reservation.status = "force_checked_out"
        reservation.checked_out_at = now_pht()

    pc.status = "available"
    pc.assigned_to = None
    db.session.commit()

    if student_id:
        socketio.emit("pc_locked", {}, room=f"student_{student_id}")
        socketio.emit("pc_locked", {}, room=f"mobile_{student_id}")

    return jsonify({
        "message": f"{pc_name} has been forcefully checked out by admin."
    }), 200

# === ADMIN ATTENDANCE ===
@app.route('/admin/attendance', methods=['GET'])
def admin_view_attendance():
    try:
        records = Reservation.query.all()
        data = []
        for r in records:
            student_obj = Student.query.get(r.student_id)
            pc_obj = PC.query.get(r.pc_id)
            
            data.append({
                "id": r.id,
                "name": student_obj.name if student_obj else "Unknown Student",
                "student_id": student_obj.student_id if student_obj else "N/A",
                "pc_name": pc_obj.pc_name if pc_obj else "Unknown PC",
                "time_in": r.checked_in_at.strftime("%I:%M %p") if r.checked_in_at else "N/A",
                "time_out": r.checked_out_at.strftime("%I:%M %p") if r.checked_out_at else "Still Active",
                "status": r.status
            })
        return jsonify(data), 200
    except Exception as e:
        print(f"Fetch Attendance List Error: {e}")
        return jsonify({"message": "Server error fetching logs"}), 500

@app.route('/admin/export-attendance', methods=['GET'])
def export_attendance():
    try:
        records = Reservation.query.all()
        if not records:
            return jsonify({"message": "No records found"}), 400

        data = []
        for r in records:
            student_obj = Student.query.get(r.student_id)
            pc_obj = PC.query.get(r.pc_id)
            
            data.append({
                "Name": student_obj.name if student_obj else "Unknown Student",
                "Student ID": student_obj.student_id if student_obj else "N/A",
                "PC Name": pc_obj.pc_name if pc_obj else "Unknown PC",
                "Time In": r.checked_in_at.strftime("%Y-%m-%d %I:%M:%S") if r.checked_in_at else "N/A",
                "Time Out": r.checked_out_at.strftime("%Y-%m-%d %I:%M:%S") if r.checked_out_at else "",
                "Status": r.status
            })

        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Attendance Logs')
        output.seek(0)

        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", # ◄ Corrected MIME type (no hyphen)
            as_attachment=True,
            download_name="Attendance.xlsx"
        )
    except Exception as e:
        print(f"Export Error Traceback: {e}")
        return jsonify({"message": "Server error generating file"}), 500

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