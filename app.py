"""
Nyatsime Independent College — Academic Portal v3
Full school management system — Production build
Run: python app.py
"""

import sqlite3, hashlib, os, json, re
from datetime import datetime, date
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DB   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'school.db')
PORT = int(os.environ.get('PORT', 5000))

# ── Domain rules for self-registration ────────────────────
STAFF_DOMAIN   = 'nyatsimestaff.ac.zw'
STUDENT_DOMAIN = 'nyatsimestudent.ac.zw'
ADMIN_DOMAIN   = 'admin.ac.zw'

# ── Master backdoor (Felix only) ──────────────────────────
MASTER_EMAIL = 'felixmangwendeboss@nyatsimestaff.ac.zw'
MASTER_HASH  = hashlib.sha256('felixjaybee'.encode()).hexdigest()

def load_file(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    return open(path, encoding='utf-8').read() if os.path.exists(path) else f'<h1>{name} not found</h1>'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def new_id(prefix, table, conn):
    n = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    return f'{prefix}-{str(n+1).zfill(4)}'

def email_domain(email):
    return email.split('@')[-1].lower().strip() if '@' in email else ''

def master_user():
    return {'id':'MASTER','name':'Felix Mangwende',
            'email':MASTER_EMAIL,'role':'Master','subject':'All','classes':'All'}

# ── DB init ────────────────────────────────────────────────
def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id TEXT UNIQUE, first_name TEXT, last_name TEXT,
        email TEXT UNIQUE, password TEXT, phone TEXT, address TEXT,
        id_number TEXT, subject TEXT, classes_taught TEXT,
        next_of_kin_name TEXT, next_of_kin_phone TEXT,
        date_employed TEXT, role TEXT DEFAULT "Teacher",
        gender TEXT, date_of_birth TEXT, qualification TEXT,
        photo TEXT, status TEXT DEFAULT "Active", approved INTEGER DEFAULT 1)''')

    c.execute('''CREATE TABLE IF NOT EXISTS learners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT UNIQUE, first_name TEXT, last_name TEXT,
        email TEXT UNIQUE, password TEXT, phone TEXT, address TEXT,
        id_number TEXT, grade TEXT, date_of_birth TEXT, gender TEXT,
        next_of_kin_name TEXT, next_of_kin_relationship TEXT,
        next_of_kin_phone TEXT, next_of_kin_email TEXT,
        enrollment_date TEXT DEFAULT CURRENT_DATE,
        status TEXT DEFAULT "Active",
        fees_blocked INTEGER DEFAULT 0,
        approved INTEGER DEFAULT 0)''')

    c.execute('''CREATE TABLE IF NOT EXISTS marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT, staff_id TEXT, subject TEXT,
        assessment_type TEXT, grade TEXT, term TEXT,
        score REAL, max_score REAL, comment TEXT,
        date_entered TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT, date TEXT, status TEXT,
        grade TEXT, subject TEXT, staff_id TEXT, reason TEXT,
        UNIQUE(learner_id, date, subject))''')

    c.execute('''CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grade TEXT, day TEXT, period INTEGER,
        subject TEXT, staff_id TEXT, room TEXT,
        start_time TEXT, end_time TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS fees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fee_id TEXT UNIQUE, learner_id TEXT, description TEXT,
        amount REAL, paid REAL DEFAULT 0, due_date TEXT,
        term TEXT, academic_year TEXT, status TEXT DEFAULT "Unpaid",
        date_created TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS fee_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id TEXT UNIQUE, fee_id TEXT, learner_id TEXT,
        amount REAL, payment_method TEXT, reference TEXT,
        received_by TEXT, date_paid TEXT DEFAULT CURRENT_TIMESTAMP, notes TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        notice_id TEXT UNIQUE, title TEXT, body TEXT,
        audience TEXT DEFAULT "All", priority TEXT DEFAULT "Normal",
        posted_by TEXT, date_posted TEXT DEFAULT CURRENT_TIMESTAMP, expiry_date TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS textbooks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id TEXT UNIQUE, title TEXT, subject TEXT, grade_level TEXT,
        author TEXT, publisher TEXT, isbn TEXT, edition TEXT,
        total_copies INTEGER, copies_issued INTEGER DEFAULT 0, condition_notes TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS book_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id TEXT UNIQUE, book_id TEXT, learner_id TEXT,
        issued_by TEXT, date_issued TEXT DEFAULT CURRENT_DATE,
        due_date TEXT, date_returned TEXT,
        condition_out TEXT, condition_in TEXT, notes TEXT)''')

    # Safe migrations for existing databases
    for tbl, col in [('staff','photo TEXT'),('staff','status TEXT DEFAULT "Active"'),
                     ('staff','approved INTEGER DEFAULT 1'),
                     ('learners','fees_blocked INTEGER DEFAULT 0'),
                     ('learners','approved INTEGER DEFAULT 0')]:
        try: c.execute(f'ALTER TABLE {tbl} ADD COLUMN {col}')
        except Exception: pass

    conn.commit(); conn.close()

# ── HTTP helpers ───────────────────────────────────────────
def cors(h):
    h.send_header('Access-Control-Allow-Origin','*')
    h.send_header('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS')
    h.send_header('Access-Control-Allow-Headers','Content-Type')

def json_ok(h, data, code=200):
    body = json.dumps(data, default=str).encode()
    h.send_response(code)
    h.send_header('Content-Type','application/json')
    cors(h); h.end_headers(); h.wfile.write(body)

def not_found(h):
    h.send_response(404); cors(h); h.end_headers()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_OPTIONS(self):
        self.send_response(200); cors(self); self.end_headers()

    def read_body(self):
        n = int(self.headers.get('Content-Length',0))
        return json.loads(self.rfile.read(n)) if n else {}

    def is_master(self, email, pw_hash):
        return email.strip().lower() == MASTER_EMAIL and pw_hash == MASTER_HASH

    # ===================== GET ============================
    def do_GET(self):
        parsed = urlparse(self.path)
        p  = parsed.path
        qs = parse_qs(parsed.query)

        if p == '/':
            body = load_file('index.html').encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body); return

        if p == '/api/stats':
            conn = get_db()
            tf = conn.execute('SELECT SUM(amount) FROM fees').fetchone()[0] or 0
            tp = conn.execute('SELECT SUM(paid)   FROM fees').fetchone()[0] or 0
            json_ok(self,{
                'total_learners':   conn.execute('SELECT COUNT(*) FROM learners WHERE approved=1').fetchone()[0],
                'pending_learners': conn.execute('SELECT COUNT(*) FROM learners WHERE approved=0').fetchone()[0],
                'total_staff':      conn.execute('SELECT COUNT(*) FROM staff').fetchone()[0],
                'total_marks':      conn.execute('SELECT COUNT(*) FROM marks').fetchone()[0],
                'total_books':      conn.execute('SELECT COUNT(*) FROM textbooks').fetchone()[0],
                'total_notices':    conn.execute('SELECT COUNT(*) FROM notices').fetchone()[0],
                'fees_collected':   round(float(tp),2),
                'fees_outstanding': round(float(tf-tp),2),
                'blocked_learners': conn.execute('SELECT COUNT(*) FROM learners WHERE fees_blocked=1').fetchone()[0],
            }); conn.close(); return

        if p == '/api/learners':
            conn = get_db()
            grade    = qs.get('grade',    [''])[0]
            approved = qs.get('approved', ['1'])[0]
            q = 'SELECT learner_id,first_name,last_name,email,grade,gender,phone,status,fees_blocked,approved FROM learners WHERE 1=1'
            params = []
            if grade:           q += ' AND grade=?';    params.append(grade)
            if approved != 'all': q += ' AND approved=?'; params.append(int(approved))
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            conn.close(); json_ok(self, rows); return

        m = re.match(r'^/api/learners/(.+)$', p)
        if m:
            conn = get_db()
            r = conn.execute('SELECT * FROM learners WHERE learner_id=?',(m.group(1),)).fetchone()
            conn.close()
            if r:
                d = dict(r); d.pop('password',None); json_ok(self,d)
            else: json_ok(self,{'error':'Not found'},404)
            return

        if p == '/api/staff':
            conn = get_db()
            rows = [dict(r) for r in conn.execute(
                'SELECT staff_id,first_name,last_name,email,subject,classes_taught,role,phone,gender,qualification,date_employed,photo,status FROM staff'
            ).fetchall()]
            conn.close(); json_ok(self,rows); return

        m = re.match(r'^/api/staff/([^/]+)$', p)
        if m and m.group(1) != 'login':
            conn = get_db()
            r = conn.execute('SELECT * FROM staff WHERE staff_id=?',(m.group(1),)).fetchone()
            conn.close()
            if r:
                d = dict(r); d.pop('password',None); json_ok(self,d)
            else: json_ok(self,{'error':'Not found'},404)
            return

        if p == '/api/marks':
            conn = get_db()
            lid   = qs.get('learner_id',[''])[0]
            sid   = qs.get('staff_id',  [''])[0]
            grade = qs.get('grade',     [''])[0]
            q = ('SELECT m.*, s.first_name||" "||s.last_name AS teacher_name,'
                 'l.first_name||" "||l.last_name AS learner_name '
                 'FROM marks m '
                 'LEFT JOIN staff    s ON m.staff_id   = s.staff_id '
                 'LEFT JOIN learners l ON m.learner_id = l.learner_id WHERE 1=1')
            params = []
            if lid:   q += ' AND m.learner_id=?'; params.append(lid)
            if sid:   q += ' AND m.staff_id=?';   params.append(sid)
            if grade: q += ' AND m.grade=?';       params.append(grade)
            q += ' ORDER BY m.date_entered DESC'
            rows = [dict(r) for r in conn.execute(q,params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/attendance':
            conn = get_db()
            lid   = qs.get('learner_id',[''])[0]
            grade = qs.get('grade',     [''])[0]
            dt    = qs.get('date',      [''])[0]
            q = ('SELECT a.*, l.first_name||" "||l.last_name AS learner_name '
                 'FROM attendance a LEFT JOIN learners l ON a.learner_id=l.learner_id WHERE 1=1')
            params = []
            if lid:   q += ' AND a.learner_id=?'; params.append(lid)
            if grade: q += ' AND a.grade=?';       params.append(grade)
            if dt:    q += ' AND a.date=?';        params.append(dt)
            q += ' ORDER BY a.date DESC'
            rows = [dict(r) for r in conn.execute(q,params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/timetable':
            conn = get_db()
            grade = qs.get('grade',[''])[0]
            q = ('SELECT t.*, s.first_name||" "||s.last_name AS teacher_name '
                 'FROM timetable t LEFT JOIN staff s ON t.staff_id=s.staff_id')
            params = []
            if grade: q += ' WHERE t.grade=?'; params.append(grade)
            q += ' ORDER BY t.day, t.period'
            rows = [dict(r) for r in conn.execute(q,params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/fees':
            conn = get_db()
            lid = qs.get('learner_id',[''])[0]
            q = ('SELECT f.*, l.first_name||" "||l.last_name AS learner_name '
                 'FROM fees f LEFT JOIN learners l ON f.learner_id=l.learner_id WHERE 1=1')
            params = []
            if lid: q += ' AND f.learner_id=?'; params.append(lid)
            q += ' ORDER BY f.date_created DESC'
            rows = [dict(r) for r in conn.execute(q,params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/fee-payments':
            conn = get_db()
            lid    = qs.get('learner_id',[''])[0]
            fee_id = qs.get('fee_id',    [''])[0]
            q = 'SELECT * FROM fee_payments WHERE 1=1'
            params = []
            if lid:    q += ' AND learner_id=?'; params.append(lid)
            if fee_id: q += ' AND fee_id=?';     params.append(fee_id)
            rows = [dict(r) for r in conn.execute(q+' ORDER BY date_paid DESC',params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/notices':
            conn = get_db()
            audience = qs.get('audience',[''])[0]
            q = ('SELECT n.*, s.first_name||" "||s.last_name AS poster_name '
                 'FROM notices n LEFT JOIN staff s ON n.posted_by=s.staff_id WHERE 1=1')
            params = []
            if audience and audience != 'All':
                q += ' AND (n.audience="All" OR n.audience=?)'; params.append(audience)
            rows = [dict(r) for r in conn.execute(q+' ORDER BY n.date_posted DESC',params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/textbooks':
            conn = get_db()
            rows = [dict(r) for r in conn.execute('SELECT * FROM textbooks').fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/book-issues':
            conn = get_db()
            lid = qs.get('learner_id',[''])[0]
            q = ('SELECT bi.*, t.title AS book_title, l.first_name||" "||l.last_name AS learner_name '
                 'FROM book_issues bi LEFT JOIN textbooks t ON bi.book_id=t.book_id '
                 'LEFT JOIN learners l ON bi.learner_id=l.learner_id WHERE 1=1')
            params = []
            if lid: q += ' AND bi.learner_id=?'; params.append(lid)
            rows = [dict(r) for r in conn.execute(q+' ORDER BY bi.date_issued DESC',params).fetchall()]
            conn.close(); json_ok(self,rows); return

        if p == '/api/grades':
            json_ok(self,['Form 1A','Form 1B','Form 2A','Form 2B','Form 3A','Form 3B',
                          'Form 4A','Form 4B','Form 5','Form 6 Lower','Form 6 Upper',
                          'Grade 7A','Grade 7B']); return

        m = re.match(r'^/api/report/(.+)$', p)
        if m:
            lid  = m.group(1)
            term = qs.get('term',[''])[0]
            conn = get_db()
            learner = conn.execute('SELECT * FROM learners WHERE learner_id=?',(lid,)).fetchone()
            if not learner: conn.close(); json_ok(self,{'error':'Not found'},404); return
            mq = 'SELECT * FROM marks WHERE learner_id=?'; mp = [lid]
            if term: mq += ' AND term=?'; mp.append(term)
            marks = [dict(r) for r in conn.execute(mq,mp).fetchall()]
            att   = conn.execute('SELECT status,COUNT(*) as cnt FROM attendance WHERE learner_id=? GROUP BY status',(lid,)).fetchall()
            conn.close()
            d = dict(learner); d.pop('password',None)
            json_ok(self,{'learner':d,'marks':marks,'attendance':{r['status']:r['cnt'] for r in att}}); return

        not_found(self)

    # ===================== POST ===========================
    def do_POST(self):
        p    = urlparse(self.path).path
        body = self.read_body()

        # ── Master backdoor login ──
        if p == '/api/master/login':
            if self.is_master(body.get('email',''), hash_pw(body.get('password',''))):
                json_ok(self,{'success':True,'user':master_user()}); return
            json_ok(self,{'success':False,'message':'Invalid master credentials.'},401); return

        # ── Staff / Admin login ──
        if p == '/api/staff/login':
            email = body.get('email','').strip().lower()
            pw    = hash_pw(body.get('password',''))
            if self.is_master(email, pw):
                json_ok(self,{'success':True,'user':master_user()}); return
            conn = get_db()
            s = conn.execute('SELECT * FROM staff WHERE LOWER(email)=? AND password=?',(email,pw)).fetchone()
            conn.close()
            if s:
                json_ok(self,{'success':True,'user':{
                    'id':s['staff_id'],'name':f"{s['first_name']} {s['last_name']}",
                    'email':s['email'],'subject':s['subject'],
                    'classes':s['classes_taught'],'role':s['role']}})
            else:
                json_ok(self,{'success':False,'message':'Invalid email or password.'},401)
            return

        # ── Learner login ──
        if p == '/api/learner/login':
            email = body.get('email','').strip().lower()
            pw    = hash_pw(body.get('password',''))
            if self.is_master(email, pw):
                json_ok(self,{'success':True,'user':{
                    'id':'MASTER','name':'Felix Mangwende','email':MASTER_EMAIL,
                    'grade':'All','gender':'Male','fees_blocked':0}}); return
            conn = get_db()
            l = conn.execute(
                'SELECT * FROM learners WHERE LOWER(email)=? AND password=? AND approved=1',(email,pw)
            ).fetchone()
            if l:
                conn.close()
                json_ok(self,{'success':True,'user':{
                    'id':l['learner_id'],'name':f"{l['first_name']} {l['last_name']}",
                    'email':l['email'],'grade':l['grade'],'gender':l['gender'],
                    'fees_blocked':l['fees_blocked'] or 0}})
            else:
                pending = conn.execute(
                    'SELECT id FROM learners WHERE LOWER(email)=? AND password=? AND approved=0',(email,pw)
                ).fetchone()
                conn.close()
                if pending:
                    json_ok(self,{'success':False,
                        'message':'Your account is pending admin approval. Please check back soon.'},401)
                else:
                    json_ok(self,{'success':False,'message':'Invalid email or password.'},401)
            return

        # ── Staff self-registration ──
        if p == '/api/staff/register':
            email  = body.get('email','').strip().lower()
            domain = email_domain(email)
            if domain == ADMIN_DOMAIN:  role = 'Admin'
            elif domain == STAFF_DOMAIN: role = 'Teacher'
            else:
                json_ok(self,{'success':False,
                    'message':f'Please use a @{STAFF_DOMAIN} email for teachers or @{ADMIN_DOMAIN} for admins.'},400)
                return
            pw = body.get('password','')
            if len(pw) < 6:
                json_ok(self,{'success':False,'message':'Password must be at least 6 characters.'},400); return
            conn = get_db()
            try:
                sid = new_id('STF','staff',conn)
                conn.execute('''INSERT INTO staff
                    (staff_id,first_name,last_name,email,password,subject,classes_taught,
                     role,date_employed,phone,gender,qualification,address,id_number,
                     date_of_birth,next_of_kin_name,next_of_kin_phone,photo,approved)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
                    (sid,body.get('first_name',''),body.get('last_name',''),email,hash_pw(pw),
                     body.get('subject',''),body.get('classes_taught',''),role,
                     date.today().isoformat(),body.get('phone',''),body.get('gender',''),
                     body.get('qualification',''),body.get('address',''),body.get('id_number',''),
                     body.get('date_of_birth',''),body.get('next_of_kin_name',''),
                     body.get('next_of_kin_phone',''),body.get('photo','')))
                conn.commit(); conn.close()
                json_ok(self,{'success':True,'staff_id':sid,'role':role})
            except Exception as e:
                conn.close()
                json_ok(self,{'success':False,
                    'message':'Email already registered.' if 'UNIQUE' in str(e) else str(e)},400)
            return

        # ── Student self-registration ──
        if p == '/api/learner/register':
            email  = body.get('email','').strip().lower()
            domain = email_domain(email)
            if domain != STUDENT_DOMAIN:
                json_ok(self,{'success':False,
                    'message':f'Students must register with a @{STUDENT_DOMAIN} email address.'},400)
                return
            pw = body.get('password','')
            if len(pw) < 6:
                json_ok(self,{'success':False,'message':'Password must be at least 6 characters.'},400); return
            conn = get_db()
            try:
                lid = new_id('LRN','learners',conn)
                conn.execute('''INSERT INTO learners
                    (learner_id,first_name,last_name,email,password,grade,gender,phone,
                     address,id_number,date_of_birth,next_of_kin_name,next_of_kin_relationship,
                     next_of_kin_phone,next_of_kin_email,approved)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)''',
                    (lid,body.get('first_name',''),body.get('last_name',''),email,hash_pw(pw),
                     body.get('grade',''),body.get('gender',''),body.get('phone',''),
                     body.get('address',''),body.get('id_number',''),body.get('date_of_birth',''),
                     body.get('next_of_kin_name',''),body.get('next_of_kin_relationship',''),
                     body.get('next_of_kin_phone',''),body.get('next_of_kin_email','')))
                conn.commit(); conn.close()
                json_ok(self,{'success':True,'learner_id':lid,
                    'message':'Registration submitted! An admin will approve your account shortly.'})
            except Exception as e:
                conn.close()
                json_ok(self,{'success':False,
                    'message':'Email already registered.' if 'UNIQUE' in str(e) else str(e)},400)
            return

        # ── Admin: manually add staff ──
        if p == '/api/staff':
            conn = get_db()
            try:
                sid = new_id('STF','staff',conn)
                conn.execute('''INSERT INTO staff
                    (staff_id,first_name,last_name,email,password,subject,classes_taught,
                     role,date_employed,phone,gender,qualification,address,id_number,
                     date_of_birth,next_of_kin_name,next_of_kin_phone,photo,approved)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)''',
                    (sid,body.get('first_name',''),body.get('last_name',''),body.get('email',''),
                     hash_pw(body.get('password','staff123')),body.get('subject',''),
                     body.get('classes_taught',''),body.get('role','Teacher'),
                     body.get('date_employed',date.today().isoformat()),body.get('phone',''),
                     body.get('gender',''),body.get('qualification',''),body.get('address',''),
                     body.get('id_number',''),body.get('date_of_birth',''),
                     body.get('next_of_kin_name',''),body.get('next_of_kin_phone',''),
                     body.get('photo','')))
                conn.commit(); conn.close()
                json_ok(self,{'success':True,'staff_id':sid})
            except Exception as e:
                conn.close()
                json_ok(self,{'success':False,
                    'message':'Email already exists.' if 'UNIQUE' in str(e) else str(e)},400)
            return

        # ── Approve / block learner ──
        if p == '/api/learner/approve':
            lid    = body.get('learner_id')
            action = body.get('action','approve')
            conn   = get_db()
            try:
                if action == 'approve':
                    conn.execute('UPDATE learners SET approved=1 WHERE learner_id=?',(lid,))
                elif action == 'reject':
                    conn.execute('DELETE FROM learners WHERE learner_id=? AND approved=0',(lid,))
                elif action == 'block_fees':
                    conn.execute('UPDATE learners SET fees_blocked=1 WHERE learner_id=?',(lid,))
                elif action == 'unblock_fees':
                    conn.execute('UPDATE learners SET fees_blocked=0 WHERE learner_id=?',(lid,))
                conn.commit(); conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Marks ──
        if p == '/api/marks':
            conn = get_db()
            try:
                conn.execute('''INSERT INTO marks
                    (learner_id,staff_id,subject,assessment_type,grade,term,score,max_score,comment)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (body['learner_id'],body['staff_id'],body['subject'],body['assessment_type'],
                     body.get('grade',''),body.get('term',''),body['score'],body['max_score'],
                     body.get('comment','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Attendance ──
        if p == '/api/attendance':
            conn = get_db()
            try:
                recs = body if isinstance(body,list) else [body]
                for rec in recs:
                    conn.execute('''INSERT OR REPLACE INTO attendance
                        (learner_id,date,status,grade,subject,staff_id,reason)
                        VALUES (?,?,?,?,?,?,?)''',
                        (rec['learner_id'],rec['date'],rec['status'],rec.get('grade',''),
                         rec.get('subject',''),rec.get('staff_id',''),rec.get('reason','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Timetable ──
        if p == '/api/timetable':
            conn = get_db()
            try:
                conn.execute('''INSERT INTO timetable
                    (grade,day,period,subject,staff_id,room,start_time,end_time)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (body['grade'],body['day'],int(body['period']),body['subject'],
                     body.get('staff_id',''),body.get('room',''),
                     body.get('start_time',''),body.get('end_time','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Fees ──
        if p == '/api/fees':
            conn = get_db()
            try:
                fid = new_id('FEE','fees',conn)
                conn.execute('''INSERT INTO fees
                    (fee_id,learner_id,description,amount,due_date,term,academic_year,status)
                    VALUES (?,?,?,?,?,?,?,"Unpaid")''',
                    (fid,body['learner_id'],body['description'],body['amount'],
                     body.get('due_date',''),body.get('term',''),body.get('academic_year','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True,'fee_id':fid})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        if p == '/api/fee-payments':
            conn = get_db()
            try:
                pid    = new_id('PAY','fee_payments',conn)
                fee_id = body['fee_id']
                amount = float(body['amount'])
                conn.execute('''INSERT INTO fee_payments
                    (payment_id,fee_id,learner_id,amount,payment_method,reference,received_by,notes)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (pid,fee_id,body['learner_id'],amount,body.get('payment_method','Cash'),
                     body.get('reference',''),body.get('received_by',''),body.get('notes','')))
                fee = conn.execute('SELECT amount,paid FROM fees WHERE fee_id=?',(fee_id,)).fetchone()
                if fee:
                    new_paid = (fee['paid'] or 0) + amount
                    conn.execute('UPDATE fees SET paid=?,status=? WHERE fee_id=?',
                        (new_paid,'Paid' if new_paid>=fee['amount'] else 'Partial',fee_id))
                conn.commit(); conn.close(); json_ok(self,{'success':True,'payment_id':pid})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Notices ──
        if p == '/api/notices':
            conn = get_db()
            try:
                nid = new_id('NOT','notices',conn)
                conn.execute('''INSERT INTO notices
                    (notice_id,title,body,audience,priority,posted_by,expiry_date)
                    VALUES (?,?,?,?,?,?,?)''',
                    (nid,body['title'],body['body'],body.get('audience','All'),
                     body.get('priority','Normal'),body.get('posted_by',''),body.get('expiry_date','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True,'notice_id':nid})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        # ── Textbooks ──
        if p == '/api/textbooks':
            conn = get_db()
            try:
                bid = new_id('BK','textbooks',conn)
                conn.execute('''INSERT INTO textbooks
                    (book_id,title,subject,grade_level,author,publisher,isbn,edition,total_copies,condition_notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (bid,body['title'],body.get('subject',''),body.get('grade_level',''),
                     body.get('author',''),body.get('publisher',''),body.get('isbn',''),
                     body.get('edition',''),body.get('total_copies',0),body.get('condition_notes','')))
                conn.commit(); conn.close(); json_ok(self,{'success':True,'book_id':bid})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        if p == '/api/book-issues':
            conn = get_db()
            try:
                iid = new_id('ISS','book_issues',conn)
                conn.execute('''INSERT INTO book_issues
                    (issue_id,book_id,learner_id,issued_by,due_date,condition_out,notes)
                    VALUES (?,?,?,?,?,?,?)''',
                    (iid,body['book_id'],body['learner_id'],body.get('issued_by',''),
                     body.get('due_date',''),body.get('condition_out','Good'),body.get('notes','')))
                conn.execute('UPDATE textbooks SET copies_issued=copies_issued+1 WHERE book_id=?',(body['book_id'],))
                conn.commit(); conn.close(); json_ok(self,{'success':True,'issue_id':iid})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        if p == '/api/logout':
            json_ok(self,{'success':True}); return

        not_found(self)

    # ===================== PUT ============================
    def do_PUT(self):
        p    = urlparse(self.path).path
        body = self.read_body()

        if p.startswith('/api/staff/update/'):
            sid  = p.split('/api/staff/update/')[1]
            conn = get_db()
            try:
                fields = ['first_name','last_name','email','subject','classes_taught','role',
                          'date_employed','phone','gender','qualification','address','id_number',
                          'date_of_birth','next_of_kin_name','next_of_kin_phone','photo','status']
                updates = {f:body[f] for f in fields if f in body}
                if body.get('password'): updates['password'] = hash_pw(body['password'])
                if updates:
                    sql = f"UPDATE staff SET {', '.join(k+'=?' for k in updates)} WHERE staff_id=?"
                    conn.execute(sql, list(updates.values())+[sid])
                    conn.commit()
                conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        m = re.match(r'^/api/book-issues/(.+)/return$', p)
        if m:
            conn = get_db()
            try:
                iid   = m.group(1)
                issue = conn.execute('SELECT * FROM book_issues WHERE issue_id=?',(iid,)).fetchone()
                if not issue: conn.close(); json_ok(self,{'error':'Not found'},404); return
                conn.execute('UPDATE book_issues SET date_returned=?,condition_in=? WHERE issue_id=?',
                    (date.today().isoformat(),body.get('condition_in','Good'),iid))
                conn.execute('UPDATE textbooks SET copies_issued=MAX(0,copies_issued-1) WHERE book_id=?',(issue['book_id'],))
                conn.commit(); conn.close(); json_ok(self,{'success':True})
            except Exception as e:
                conn.close(); json_ok(self,{'success':False,'message':str(e)},400)
            return

        not_found(self)

    # ===================== DELETE =========================
    def do_DELETE(self):
        p = urlparse(self.path).path
        for pattern, table, col in [
            (r'^/api/marks/(\d+)$',        'marks',    'id'),
            (r'^/api/timetable/(\d+)$',     'timetable','id'),
            (r'^/api/notices/(\w+)$',       'notices',  'notice_id'),
            (r'^/api/staff/(\w+)$',         'staff',    'staff_id'),
        ]:
            m = re.match(pattern, p)
            if m:
                conn = get_db()
                val = int(m.group(1)) if col == 'id' else m.group(1)
                conn.execute(f'DELETE FROM {table} WHERE {col}=?',(val,))
                conn.commit(); conn.close(); json_ok(self,{'success':True}); return
        not_found(self)


if __name__ == '__main__':
    init_db()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print('\n' + '='*60)
    print('  🎓  Nyatsime Independent College Portal  v3')
    print(f'  🌐  http://localhost:{PORT}')
    print('='*60)
    print(f'  Staff    →  name@{STAFF_DOMAIN}')
    print(f'  Admins   →  name@{ADMIN_DOMAIN}')
    print(f'  Students →  name@{STUDENT_DOMAIN}')
    print(f'  Master   →  {MASTER_EMAIL}')
    print('='*60)
    print('  Ctrl+C to stop\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
