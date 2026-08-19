from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, make_response, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, qrcode, base64, io, time, socket, uuid, os
from datetime import datetime, timedelta
import pandas as pd
from fpdf import FPDF
from analytics import get_dashboard_analytics, get_student_profile

app = Flask(__name__)
app.secret_key = 'ztoptima_super_secret_key'

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) 
        ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"

# --- AUTH & PWA ---
@app.route('/manifest.json')
def manifest(): return send_from_directory('static', 'manifest.json')
@app.route('/sw.js')
def service_worker(): return send_from_directory('static', 'sw.js')

@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('teacher_dash') if session['role'] == 'teacher' else url_for('student_dash'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    user_id = request.form['user_id']
    password = request.form['password']
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['user_id']
        session['username'] = user['username']
        session['role'] = user['role']
        resp = make_response(redirect(url_for('teacher_dash') if user['role'] == 'teacher' else url_for('student_dash')))
        if user['role'] == 'student' and not request.cookies.get('device_id'):
            resp.set_cookie('device_id', str(uuid.uuid4()), max_age=60*60*24*365)
        return resp
    flash("Invalid Credentials.", "error")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- TEACHER DASHBOARD & AUTOMATION ---
@app.route('/teacher', methods=['GET', 'POST'])
def teacher_dash():
    if session.get('role') != 'teacher': return redirect(url_for('index'))
    conn = get_db_connection()
    subjects = conn.execute('SELECT * FROM subjects WHERE teacher_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    
    active_session_sub = request.form['sub_id'] if request.method == 'POST' else None
    current_date = datetime.now().strftime('%Y-%m-%d')
    kpis, at_risk, subj_chart, trend_chart = get_dashboard_analytics(current_date)
    
    return render_template('teacher_dash.html', subjects=subjects, active_session_sub=active_session_sub, 
                           current_date=current_date, kpis=kpis, at_risk=at_risk, 
                           subj_chart=subj_chart, trend_chart=trend_chart)

@app.route('/api/lock_class', methods=['POST'])
def lock_class():
    if session.get('role') != 'teacher': return jsonify(error="Unauthorized")
    data = request.json
    conn = get_db_connection()
    
    conn.execute("""
        INSERT INTO attendance_logs (student_id, sub_id, timestamp, status)
        SELECT user_id, ?, ?, 'ABSENT'
        FROM users 
        WHERE role = 'student' AND user_id NOT IN (
            SELECT student_id FROM attendance_logs WHERE sub_id = ? AND date(timestamp) = ?
        )
    """, (data['sub_id'], f"{data['date']} 12:00:00", data['sub_id'], data['date']))
    conn.commit(); conn.close()
    return jsonify(success=True)

@app.route('/api/live_roster')
def live_roster():
    sub_id = request.args.get('sub_id')
    date_val = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db_connection()
    roster = conn.execute("""
        SELECT u.user_id, u.username, 
               CASE WHEN a.log_id IS NOT NULL THEN a.status ELSE 'ABSENT' END as status,
               strftime('%I:%M %p', a.timestamp) as scan_time
        FROM users u
        LEFT JOIN attendance_logs a ON u.user_id = a.student_id AND a.sub_id = ? AND date(a.timestamp) = ?
        WHERE u.role = 'student'
    """, (sub_id, date_val)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in roster])

@app.route('/api/toggle_attendance', methods=['POST'])
def toggle_attendance():
    if session.get('role') != 'teacher': return jsonify(error="Unauthorized")
    data = request.json
    conn = get_db_connection()
    
    existing = conn.execute("SELECT * FROM attendance_logs WHERE student_id=? AND sub_id=? AND date(timestamp)=?", (data['student_id'], data['sub_id'], data['date'])).fetchone()
    if data['status'] == 'ABSENT':
        if not existing:
            conn.execute("INSERT INTO attendance_logs (student_id, sub_id, timestamp, status) VALUES (?, ?, ?, 'PRESENT')", (data['student_id'], data['sub_id'], f"{data['date']} 12:00:00"))
    else:
        conn.execute("DELETE FROM attendance_logs WHERE student_id = ? AND sub_id = ? AND date(timestamp) = ?", (data['student_id'], data['sub_id'], data['date']))
    conn.commit(); conn.close()
    return jsonify(success=True)

@app.route('/api/teacher_events')
def teacher_events():
    if session.get('role') != 'teacher': return jsonify([])
    conn = get_db_connection()
    sessions = conn.execute("SELECT sub_id, date(timestamp) as date FROM attendance_logs GROUP BY sub_id, date(timestamp)").fetchall()
    conn.close()
    return jsonify([{'title': f"{r['sub_id']} Class", 'start': r['date'], 'color': '#3b82f6'} for r in sessions])

# --- CRUD SUBJECTS & STUDENTS ---
@app.route('/subjects', methods=['GET', 'POST'])
def manage_subjects():
    if session.get('role') != 'teacher': return redirect(url_for('index'))
    conn = get_db_connection()
    if request.method == 'POST':
        if request.form.get('action') == 'delete':
            conn.execute('DELETE FROM subjects WHERE sub_id=?', (request.form['sub_id'],))
        elif request.form.get('action') == 'edit':
            conn.execute('UPDATE subjects SET sub_id=?, sub_name=? WHERE sub_id=?', (request.form['new_id'].upper(), request.form['new_name'], request.form['old_id']))
            conn.execute('UPDATE attendance_logs SET sub_id=? WHERE sub_id=?', (request.form['new_id'].upper(), request.form['old_id']))
            flash("Subject Updated!", "success")
        else:
            conn.execute('INSERT INTO subjects (sub_id, sub_name, teacher_id) VALUES (?, ?, ?)', (request.form['sub_id'].upper(), request.form['sub_name'], session['user_id']))
        conn.commit()
    subjects = conn.execute('SELECT * FROM subjects WHERE teacher_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('manage_subjects.html', subjects=subjects)

@app.route('/students', methods=['GET', 'POST'])
def manage_students():
    if session.get('role') != 'teacher': return redirect(url_for('index'))
    conn = get_db_connection()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            conn.execute('DELETE FROM users WHERE user_id=?', (request.form['user_id'],))
        elif action == 'edit':
            conn.execute('UPDATE users SET user_id=?, username=? WHERE user_id=?', (request.form['new_id'].upper(), request.form['new_name'], request.form['old_id']))
            conn.execute('UPDATE attendance_logs SET student_id=? WHERE student_id=?', (request.form['new_id'].upper(), request.form['old_id']))
        elif action == 'unbind':
            conn.execute('UPDATE users SET device_id=NULL WHERE user_id=?', (request.form['user_id'],))
            flash("Device Unbound!", "success")
        elif action == 'upload_csv':
            file = request.files['file']
            if file:
                df = pd.read_csv(file)
                for _, row in df.iterrows():
                    try:
                        conn.execute('INSERT INTO users (user_id, username, password, role) VALUES (?, ?, ?, ?)', 
                                     (str(row['user_id']).upper(), str(row['username']), generate_password_hash('student123'), 'student'))
                    except: pass 
                flash("CSV Uploaded successfully!", "success")
        else:
            conn.execute('INSERT INTO users (user_id, username, password, role) VALUES (?, ?, ?, ?)', (request.form['user_id'].upper(), request.form['username'], generate_password_hash('student123'), 'student'))
        conn.commit()
    students = conn.execute("SELECT * FROM users WHERE role = 'student'").fetchall()
    conn.close()
    return render_template('manage_students.html', students=students)

@app.route('/api/student_profile/<student_id>')
def student_profile(student_id):
    if session.get('role') != 'teacher': return jsonify(error="Unauthorized")
    pct = get_student_profile(student_id)
    return jsonify(percentage=pct)

# --- EXPORT REPORTS ---
@app.route('/reports')
def reports():
    if session.get('role') != 'teacher': return redirect(url_for('index'))
    current_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('reports.html', current_date=current_date)

@app.route('/export_data')
def export_data():
    date_val = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    export_type = request.args.get('type', 'pdf')
    conn = get_db_connection()
    
    query = """
        SELECT u.username, s.sub_id, CASE WHEN a.log_id IS NOT NULL THEN a.status ELSE 'ABSENT' END as status, strftime('%I:%M %p', a.timestamp) as time
        FROM users u CROSS JOIN (SELECT DISTINCT sub_id FROM attendance_logs WHERE date(timestamp) = ?) s
        LEFT JOIN attendance_logs a ON u.user_id = a.student_id AND a.sub_id = s.sub_id AND date(a.timestamp) = ?
        WHERE u.role = 'student' ORDER BY s.sub_id, u.username
    """
    logs = conn.execute(query, (date_val, date_val)).fetchall()
    conn.close()

    if export_type == 'csv':
        df = pd.DataFrame([dict(row) for row in logs])
        output = io.BytesIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(output, mimetype='text/csv', as_attachment=True, download_name=f'Attendance_{date_val}.csv')

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, txt=f"Daily Attendance Report", ln=True, align='C')
    pdf.set_font("Arial", '', 11)
    pdf.cell(190, 8, txt=f"Date: {date_val}", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(55, 10, "Student Name", border=1); pdf.cell(35, 10, "Subject", border=1); pdf.cell(40, 10, "Status", border=1); pdf.cell(60, 10, "Scan Time", border=1, ln=True)
    pdf.set_font("Arial", '', 11)
    for log in logs:
        time_str = "-" if log['status'] == 'ABSENT' else (str(log['time']) if log['time'] else "Manual Override")
        pdf.cell(55, 10, str(log['username']), border=1); pdf.cell(35, 10, str(log['sub_id']), border=1); pdf.cell(40, 10, str(log['status']), border=1); pdf.cell(60, 10, time_str, border=1, ln=True)
    pdf_buffer = io.BytesIO()
    pdf.output(pdf_buffer)
    pdf_buffer.seek(0)
    return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=f'Attendance_{date_val}.pdf')

# --- STUDENT ROUTES ---
@app.route('/student')
def student_dash():
    if session.get('role') != 'student': return redirect(url_for('index'))
    conn = get_db_connection()
    total_classes_row = conn.execute("SELECT COUNT(DISTINCT sub_id || date(timestamp)) FROM attendance_logs").fetchone()
    total_classes = total_classes_row[0] if total_classes_row else 0
    attended_row = conn.execute("SELECT COUNT(*) FROM attendance_logs WHERE student_id=? AND status='PRESENT'", (session['user_id'],)).fetchone()
    attended = attended_row[0] if attended_row else 0
    percentage = int((attended / total_classes) * 100) if total_classes > 0 else 0
    conn.close()
    return render_template('student_dash.html', percentage=percentage)

@app.route('/api/student_events')
def student_events():
    if session.get('role') != 'student': return jsonify([])
    conn = get_db_connection()
    all_sessions = conn.execute("SELECT sub_id, date(timestamp) as date FROM attendance_logs GROUP BY sub_id, date(timestamp)").fetchall()
    student_logs = conn.execute("SELECT sub_id, date(timestamp) as date FROM attendance_logs WHERE student_id = ? AND status = 'PRESENT'", (session['user_id'],)).fetchall()
    conn.close()
    attended = {f"{r['sub_id']}_{r['date']}" for r in student_logs}
    events = []
    for row in all_sessions:
        sub = row['sub_id']
        dt = row['date']
        is_present = f"{sub}_{dt}" in attended
        events.append({'title': f"{sub} ({'Present' if is_present else 'Absent'})", 'start': dt, 'color': '#10b981' if is_present else '#ef4444'})
    return jsonify(events)

@app.route('/mark_attendance')
def mark_attendance():
    if session.get('role') != 'student': return jsonify(status='error', message='Unauthorized.')
    sub_id = request.args.get('sub_id')
    token = request.args.get('token', type=int)
    student_id = session['user_id']
    device_cookie = request.cookies.get('device_id')

    if int(time.time()) - token > 15: return jsonify(status='error', message='QR Code Expired.')
    if not device_cookie: return jsonify(status='error', message='Device verification failed. Clear cache and try again.')

    conn = get_db_connection()
    user = conn.execute("SELECT device_id FROM users WHERE user_id=?", (student_id,)).fetchone()
    if not user['device_id']: conn.execute("UPDATE users SET device_id=? WHERE user_id=?", (device_cookie, student_id))
    elif user['device_id'] != device_cookie:
        conn.close()
        return jsonify(status='error', message='🚨 SECURITY ALERT: Buddy punching blocked. Device mismatch.')

    today = datetime.now().strftime('%Y-%m-%d')
    if conn.execute('SELECT * FROM attendance_logs WHERE student_id=? AND sub_id=? AND date(timestamp)=?', (student_id, sub_id, today)).fetchone():
        conn.close()
        return jsonify(status='error', message='Attendance already marked!')

    conn.execute("INSERT INTO attendance_logs (student_id, sub_id, timestamp) VALUES (?, ?, datetime('now', 'localtime'))", (student_id, sub_id))
    conn.commit()
    conn.close()
    return jsonify(status='success', message='Attendance marked successfully!')

@app.route('/api/get_qr')
def get_qr():
    sub_id = request.args.get('sub_id')
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(f"https://{get_local_ip()}:5000/mark_attendance?sub_id={sub_id}&token={int(time.time())}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return jsonify({'qr': base64.b64encode(buffered.getvalue()).decode('utf-8')})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, ssl_context='adhoc')