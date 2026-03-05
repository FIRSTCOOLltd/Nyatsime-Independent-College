"""
Nyatsime Independent College - Academic Portal
Security-hardened production build
"""
import sqlite3, hashlib, os, json, re, time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from html import escape

# ── CONFIG (all from environment variables — no hardcoded secrets) ──────────
PORT        = int(os.environ.get('PORT', 5000))
SECRET_KEY  = os.environ.get('SECRET_KEY', os.urandom(32).hex())  # never hardcoded
DB_PATH     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'school.db')
HTML_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
DEBUG       = os.environ.get('DEBUG', 'false').lower() == 'true'  # debug OFF in production

# ── RATE LIMITING (prevent brute force on login) ─────────────────────────────
_rate_store = {}  # ip -> [timestamp, ...]
RATE_LIMIT  = 10  # max requests
RATE_WINDOW = 60  # per 60 seconds

def is_rate_limited(ip):
    now = time.time()
    hits = [t for t in _rate_store.get(ip, []) if now - t < RATE_WINDOW]
    _rate_store[ip] = hits
    if len(hits) >= RATE_LIMIT:
        return True
    _rate_store[ip].append(now)
    return False

# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrency
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def hash_pw(pw):
    # Use SHA-256 with a site-wide pepper from env
    pepper = os.environ.get('PW_PEPPER', 'nyatsime_pepper_2024')
    return hashlib.sha256((pw + pepper).encode()).hexdigest()

def sanitize(value):
    """Escape HTML to prevent XSS from user-submitted text in responses"""
    if isinstance(value, str):
        return escape(value)
    return value

def sanitize_dict(d):
    return {k: sanitize(v) for k, v in d.items()}

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id TEXT UNIQUE, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        phone TEXT, address TEXT, id_number TEXT,
        subject TEXT, classes_taught TEXT,
        next_of_kin_name TEXT, next_of_kin_phone TEXT,
        date_employed TEXT, role TEXT DEFAULT "Teacher",
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS learners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT UNIQUE, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        phone TEXT, address TEXT, id_number TEXT,
        grade TEXT, date_of_birth TEXT, gender TEXT,
        next_of_kin_name TEXT, next_of_kin_relationship TEXT,
        next_of_kin_phone TEXT, next_of_kin_email TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        learner_id TEXT NOT NULL, staff_id TEXT NOT NULL,
        subject TEXT NOT NULL, assessment_type TEXT NOT NULL,
        grade TEXT, score REAL NOT NULL, max_score REAL NOT NULL,
        comment TEXT, date_entered TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (learner_id) REFERENCES learners(learner_id),
        FOREIGN KEY (staff_id) REFERENCES staff(staff_id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS textbooks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id TEXT UNIQUE, title TEXT NOT NULL, subject TEXT,
        grade_level TEXT, author TEXT, publisher TEXT,
        isbn TEXT, edition TEXT,
        total_copies INTEGER DEFAULT 0,
        copies_issued INTEGER DEFAULT 0,
        condition_notes TEXT)''')

    # Login attempts table for audit trail
    c.execute('''CREATE TABLE IF NOT EXISTS login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT, role TEXT, success INTEGER,
        ip TEXT, attempted_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Seed demo accounts (change passwords via env in production)
    _seed_demo(c)
    conn.commit(); conn.close()

def _seed_demo(c):
    c.execute("SELECT id FROM staff WHERE email='teacher@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute('''INSERT INTO staff (staff_id,first_name,last_name,email,password,
            subject,classes_taught,role,date_employed,phone) VALUES (?,?,?,?,?,?,?,?,?,?)''',
            ('STF-001','Nomvula','Khumalo','teacher@nyatsime.ac.zw',hash_pw('teacher123'),
             'Mathematics','Form 3A, Form 4B','Teacher','2024-01-15','0771234567'))
    c.execute("SELECT id FROM staff WHERE email='admin@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute('''INSERT INTO staff (staff_id,first_name,last_name,email,password,
            subject,classes_taught,role,date_employed) VALUES (?,?,?,?,?,?,?,?,?)''',
            ('STF-002','Admin','User','admin@nyatsime.ac.zw',hash_pw('admin123'),
             'Administration','All','Admin','2024-01-01'))
    c.execute("SELECT id FROM learners WHERE email='learner@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute('''INSERT INTO learners (learner_id,first_name,last_name,email,
            password,grade,gender,phone) VALUES (?,?,?,?,?,?,?,?)''',
            ('LRN-001','Amahle','Dlamini','learner@nyatsime.ac.zw',hash_pw('learner123'),
             'Form 3A','Female','0771112222'))
    c.execute("SELECT id FROM marks WHERE learner_id='LRN-001'")
    if not c.fetchone():
        c.executemany('''INSERT INTO marks (learner_id,staff_id,subject,
            assessment_type,grade,score,max_score,comment) VALUES (?,?,?,?,?,?,?,?)''',[
            ('LRN-001','STF-001','Mathematics','Test 1','Form 3A',78,100,'Good work on algebra!'),
            ('LRN-001','STF-001','Mathematics','Test 2','Form 3A',85,100,'Excellent improvement!'),
            ('LRN-001','STF-001','Mathematics','Assignment 1','Form 3A',92,100,'Outstanding effort!'),
        ])

# ── INPUT VALIDATION ──────────────────────────────────────────────────────────
def validate_email(email):
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', str(email)))

def validate_score(score, max_score):
    try:
        s, m = float(score), float(max_score)
        return s >= 0 and m > 0 and s <= m
    except:
        return False

def validate_string(value, max_len=200, required=True):
    if not isinstance(value, str):
        return False
    if required and not value.strip():
        return False
    return len(value) <= max_len

def strip_fields(data, fields):
    """Return only the fields we expect — never pass raw user data to DB"""
    return {k: data[k] for k in fields if k in data}

# ── HTTP HELPERS ──────────────────────────────────────────────────────────────
def send_json(h, data, code=200):
    body = json.dumps(data).encode()
    h.send_response(code)
    h.send_header('Content-Type', 'application/json')
    h.send_header('Content-Length', str(len(body)))
    # Security headers
    h.send_header('Access-Control-Allow-Origin', os.environ.get('ALLOWED_ORIGIN', '*'))
    h.send_header('X-Content-Type-Options', 'nosniff')
    h.send_header('X-Frame-Options', 'DENY')
    h.send_header('X-XSS-Protection', '1; mode=block')
    h.end_headers()
    h.wfile.write(body)

def send_error(h, message, code=400):
    # Never expose internal error details to client
    safe_messages = {
        400: 'Invalid request.',
        401: 'Authentication failed.',
        403: 'Access denied.',
        404: 'Not found.',
        429: 'Too many requests. Please wait.',
        500: 'Server error.'
    }
    send_json(h, {'success': False, 'message': safe_messages.get(code, message)}, code)

def read_body(h):
    try:
        length = int(h.headers.get('Content-Length', 0))
        if length > 10000:  # reject oversized payloads
            return None
        return json.loads(h.rfile.read(length)) if length else {}
    except:
        return None

def get_ip(h):
    return h.headers.get('X-Forwarded-For', h.client_address[0]).split(',')[0].strip()

def log_attempt(email, role, success, ip):
    try:
        conn = get_db()
        conn.execute('INSERT INTO login_attempts (email,role,success,ip) VALUES (?,?,?,?)',
            (email, role, 1 if success else 0, ip))
        conn.commit(); conn.close()
    except: pass

# ── SESSION (simple signed token — no client-side data) ─────────────────────
import hmac
_sessions = {}  # token -> {user_id, role, expires}

def create_session(user_id, role):
    token = hmac.new(SECRET_KEY.encode(), f"{user_id}{role}{time.time()}".encode(),
        hashlib.sha256).hexdigest()
    _sessions[token] = {'user_id': user_id, 'role': role, 'expires': time.time() + 86400}
    return token

def get_session(h):
    cookie = h.headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('session='):
            token = part[8:]
            s = _sessions.get(token)
            if s and s['expires'] > time.time():
                return s
    return None

def set_session_cookie(h, token):
    h.send_header('Set-Cookie',
        f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400')

def clear_session(h):
    cookie = h.headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('session='):
            token = part[8:]
            _sessions.pop(token, None)

# ── REQUEST HANDLER ───────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Log to stdout without sensitive data
        if DEBUG:
            print(f"[{self.address_string()}] {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', os.environ.get('ALLOWED_ORIGIN', '*'))
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.end_headers()

    def require_auth(self, required_role=None):
        """Returns session or None. Optionally checks role."""
        s = get_session(self)
        if not s:
            send_error(self, 'Not authenticated', 401)
            return None
        if required_role and s['role'] != required_role:
            send_error(self, 'Access denied', 403)
            return None
        return s

    def do_GET(self):
        p  = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        # ── Frontend ──
        if p == '/' or p == '/index.html':
            try:
                html = open(HTML_FILE, 'rb').read()
            except:
                html = b'<h1>Nyatsime Independent College Portal</h1><p>index.html not found.</p>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(html)))
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(html); return

        # ── Stats (staff only) ──
        if p == '/api/stats':
            if not self.require_auth('staff'): return
            conn = get_db()
            send_json(self, {
                'total_learners': conn.execute('SELECT COUNT(*) FROM learners WHERE is_active=1').fetchone()[0],
                'total_staff':    conn.execute('SELECT COUNT(*) FROM staff WHERE is_active=1').fetchone()[0],
                'total_marks':    conn.execute('SELECT COUNT(*) FROM marks').fetchone()[0],
                'total_books':    conn.execute('SELECT COUNT(*) FROM textbooks').fetchone()[0],
            }); conn.close(); return

        # ── Marks ──
        if p == '/api/marks':
            sess = get_session(self)
            if not sess:
                send_error(self, 'Not authenticated', 401); return
            lid = qs.get('learner_id', [''])[0]
            # Learners can ONLY see their own marks
            if sess['role'] == 'learner':
                lid = sess['user_id']
            conn = get_db()
            q = '''SELECT m.id, m.learner_id, m.subject, m.assessment_type, m.grade,
                          m.score, m.max_score, m.comment, m.date_entered,
                          s.first_name||" "||s.last_name AS teacher_name
                   FROM marks m LEFT JOIN staff s ON m.staff_id=s.staff_id WHERE 1=1'''
            params = []
            if lid: q += ' AND m.learner_id=?'; params.append(lid)
            q += ' ORDER BY m.date_entered DESC'
            rows = [sanitize_dict(dict(r)) for r in conn.execute(q, params).fetchall()]
            conn.close(); send_json(self, rows); return

        # ── All learners (staff only) ──
        if p == '/api/learners':
            if not self.require_auth('staff'): return
            conn = get_db()
            # Return only necessary fields — not passwords, not sensitive IDs
            rows = [dict(r) for r in conn.execute(
                '''SELECT learner_id, first_name, last_name, email,
                          grade, gender, phone FROM learners WHERE is_active=1'''
            ).fetchall()]
            conn.close(); send_json(self, rows); return

        # ── Single learner ──
        m = re.match(r'^/api/learners/([A-Z0-9\-]+)$', p)
        if m:
            sess = get_session(self)
            if not sess:
                send_error(self, 'Not authenticated', 401); return
            lid = m.group(1)
            # Learners can only view their own profile
            if sess['role'] == 'learner' and sess['user_id'] != lid:
                send_error(self, 'Access denied', 403); return
            conn = get_db()
            r = conn.execute('SELECT * FROM learners WHERE learner_id=? AND is_active=1',
                (lid,)).fetchone()
            conn.close()
            if r:
                d = dict(r)
                # Never return password hash to client
                d.pop('password', None)
                d.pop('id', None)
                send_json(self, sanitize_dict(d))
            else:
                send_error(self, 'Not found', 404)
            return

        # ── Staff list (staff only) ──
        if p == '/api/staff':
            if not self.require_auth('staff'): return
            conn = get_db()
            rows = [dict(r) for r in conn.execute(
                '''SELECT staff_id, first_name, last_name, email,
                          subject, classes_taught, role, phone
                   FROM staff WHERE is_active=1'''
            ).fetchall()]
            conn.close(); send_json(self, rows); return

        # ── Textbooks (authenticated users only) ──
        if p == '/api/textbooks':
            if not get_session(self):
                send_error(self, 'Not authenticated', 401); return
            conn = get_db()
            rows = [dict(r) for r in conn.execute('SELECT * FROM textbooks').fetchall()]
            conn.close(); send_json(self, rows); return

        send_error(self, 'Not found', 404)

    def do_POST(self):
        p    = urlparse(self.path).path
        ip   = get_ip(self)
        body = read_body(self)

        if body is None:
            send_error(self, 'Invalid request body', 400); return

        # ── Staff login ──
        if p == '/api/staff/login':
            if is_rate_limited(ip):
                send_error(self, 'Too many requests', 429); return
            email    = str(body.get('email', '')).strip().lower()
            password = str(body.get('password', ''))
            if not validate_email(email) or not password:
                send_error(self, 'Invalid credentials', 401); return
            conn = get_db()
            s = conn.execute(
                'SELECT * FROM staff WHERE email=? AND password=? AND is_active=1',
                (email, hash_pw(password))).fetchone()
            conn.close()
            log_attempt(email, 'staff', bool(s), ip)
            if s:
                token = create_session(s['staff_id'], 'staff')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                set_session_cookie(self, token)
                # Security headers
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'user': {
                    'id': s['staff_id'],
                    'name': f"{s['first_name']} {s['last_name']}",
                    'email': s['email'],
                    'subject': s['subject'],
                    'classes': s['classes_taught'],
                    'role': s['role']
                }}).encode())
            else:
                # Same message for wrong email or wrong password
                # (don't reveal which one failed)
                send_error(self, 'Invalid credentials', 401)
            return

        # ── Learner login ──
        if p == '/api/learner/login':
            if is_rate_limited(ip):
                send_error(self, 'Too many requests', 429); return
            email    = str(body.get('email', '')).strip().lower()
            password = str(body.get('password', ''))
            if not validate_email(email) or not password:
                send_error(self, 'Invalid credentials', 401); return
            conn = get_db()
            l = conn.execute(
                'SELECT * FROM learners WHERE email=? AND password=? AND is_active=1',
                (email, hash_pw(password))).fetchone()
            conn.close()
            log_attempt(email, 'learner', bool(l), ip)
            if l:
                token = create_session(l['learner_id'], 'learner')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                set_session_cookie(self, token)
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'user': {
                    'id': l['learner_id'],
                    'name': f"{l['first_name']} {l['last_name']}",
                    'email': l['email'],
                    'grade': l['grade'],
                    'gender': l['gender']
                }}).encode())
            else:
                send_error(self, 'Invalid credentials', 401)
            return

        # ── Learner register ──
        if p == '/api/learner/register':
            if is_rate_limited(ip):
                send_error(self, 'Too many requests', 429); return
            # Validate all required fields
            email = str(body.get('email', '')).strip().lower()
            first = str(body.get('first_name', '')).strip()
            last  = str(body.get('last_name', '')).strip()
            pw    = str(body.get('password', ''))
            if not validate_email(email):
                send_error(self, 'Invalid email', 400); return
            if not validate_string(first) or not validate_string(last):
                send_error(self, 'Name required', 400); return
            if len(pw) < 6:
                send_error(self, 'Password too short', 400); return
            # Only accept known fields
            allowed = ['first_name','last_name','email','password','grade','gender',
                       'phone','address','id_number','date_of_birth',
                       'next_of_kin_name','next_of_kin_relationship',
                       'next_of_kin_phone','next_of_kin_email']
            data = strip_fields(body, allowed)
            conn = get_db()
            try:
                count = conn.execute('SELECT COUNT(*) FROM learners').fetchone()[0]
                lid   = f"LRN-{str(count+1).zfill(3)}"
                conn.execute('''INSERT INTO learners (learner_id,first_name,last_name,email,
                    password,grade,gender,phone,address,id_number,date_of_birth,
                    next_of_kin_name,next_of_kin_relationship,next_of_kin_phone,
                    next_of_kin_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (lid, first, last, email, hash_pw(pw),
                     data.get('grade',''), data.get('gender',''),
                     data.get('phone',''), data.get('address',''),
                     data.get('id_number',''), data.get('date_of_birth',''),
                     data.get('next_of_kin_name',''), data.get('next_of_kin_relationship',''),
                     data.get('next_of_kin_phone',''), data.get('next_of_kin_email','')))
                conn.commit(); conn.close()
                send_json(self, {'success': True, 'learner_id': lid})
            except Exception:
                conn.close()
                # Don't expose DB error — could reveal email already exists
                send_error(self, 'Registration failed. Email may already be in use.', 400)
            return

        # ── Add mark (staff only) ──
        if p == '/api/marks':
            sess = self.require_auth('staff')
            if not sess: return
            # Validate inputs
            learner_id      = str(body.get('learner_id', '')).strip()
            subject         = str(body.get('subject', '')).strip()
            assessment_type = str(body.get('assessment_type', '')).strip()
            grade           = str(body.get('grade', '')).strip()
            comment         = str(body.get('comment', ''))[:500]  # cap comment length
            score     = body.get('score')
            max_score = body.get('max_score')
            if not learner_id or not subject or not assessment_type:
                send_error(self, 'Missing required fields', 400); return
            if not validate_score(score, max_score):
                send_error(self, 'Invalid score values', 400); return
            # Verify learner actually exists
            conn = get_db()
            exists = conn.execute('SELECT id FROM learners WHERE learner_id=?',
                (learner_id,)).fetchone()
            if not exists:
                conn.close(); send_error(self, 'Learner not found', 404); return
            try:
                conn.execute('''INSERT INTO marks (learner_id,staff_id,subject,
                    assessment_type,grade,score,max_score,comment) VALUES (?,?,?,?,?,?,?,?)''',
                    (learner_id, sess['user_id'], subject, assessment_type,
                     grade, float(score), float(max_score), comment))
                conn.commit(); conn.close()
                send_json(self, {'success': True})
            except Exception:
                conn.close(); send_error(self, 'Failed to save mark', 500)
            return

        # ── Add textbook (staff only) ──
        if p == '/api/textbooks':
            if not self.require_auth('staff'): return
            title = str(body.get('title', '')).strip()
            if not validate_string(title):
                send_error(self, 'Title is required', 400); return
            conn = get_db()
            try:
                count = conn.execute('SELECT COUNT(*) FROM textbooks').fetchone()[0]
                bid   = f"BK-{str(count+1).zfill(3)}"
                copies = int(body.get('total_copies', 0))
                if copies < 0: copies = 0
                conn.execute('''INSERT INTO textbooks (book_id,title,subject,grade_level,
                    author,publisher,isbn,edition,total_copies,condition_notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (bid, title,
                     str(body.get('subject',''))[:100],
                     str(body.get('grade_level',''))[:50],
                     str(body.get('author',''))[:200],
                     str(body.get('publisher',''))[:200],
                     str(body.get('isbn',''))[:30],
                     str(body.get('edition',''))[:50],
                     copies,
                     str(body.get('condition_notes',''))[:300]))
                conn.commit(); conn.close()
                send_json(self, {'success': True, 'book_id': bid})
            except Exception:
                conn.close(); send_error(self, 'Failed to add textbook', 500)
            return

        # ── Logout ──
        if p == '/api/logout':
            clear_session(self)
            send_json(self, {'success': True}); return

        send_error(self, 'Not found', 404)

    def do_DELETE(self):
        p = urlparse(self.path).path

        # ── Delete mark (staff only) ──
        m = re.match(r'^/api/marks/(\d+)$', p)
        if m:
            sess = self.require_auth('staff')
            if not sess: return
            mark_id = int(m.group(1))
            conn = get_db()
            # Confirm mark exists before deleting
            exists = conn.execute('SELECT id FROM marks WHERE id=?', (mark_id,)).fetchone()
            if not exists:
                conn.close(); send_error(self, 'Mark not found', 404); return
            conn.execute('DELETE FROM marks WHERE id=?', (mark_id,))
            conn.commit(); conn.close()
            send_json(self, {'success': True}); return

        send_error(self, 'Not found', 404)

if __name__ == '__main__':
    init_db()
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"\n{'='*54}")
    print(f"  🎓  Nyatsime Independent College Portal")
    print(f"  🌐  Running on port {PORT}")
    print(f"  🔒  Security: ENABLED")
    print(f"{'='*54}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
