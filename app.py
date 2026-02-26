import sqlite3, hashlib, os, json, re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get('PORT', 5000))
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'school.db')
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id TEXT UNIQUE, first_name TEXT, last_name TEXT, email TEXT UNIQUE, password TEXT, phone TEXT, subject TEXT, classes_taught TEXT, role TEXT DEFAULT "Teacher", date_employed TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS learners (id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT UNIQUE, first_name TEXT, last_name TEXT, email TEXT UNIQUE, password TEXT, phone TEXT, address TEXT, id_number TEXT, grade TEXT, date_of_birth TEXT, gender TEXT, next_of_kin_name TEXT, next_of_kin_relationship TEXT, next_of_kin_phone TEXT, next_of_kin_email TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS marks (id INTEGER PRIMARY KEY AUTOINCREMENT, learner_id TEXT, staff_id TEXT, subject TEXT, assessment_type TEXT, grade TEXT, score REAL, max_score REAL, comment TEXT, date_entered TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS textbooks (id INTEGER PRIMARY KEY AUTOINCREMENT, book_id TEXT UNIQUE, title TEXT, subject TEXT, grade_level TEXT, author TEXT, publisher TEXT, isbn TEXT, edition TEXT, total_copies INTEGER, copies_issued INTEGER DEFAULT 0, condition_notes TEXT)''')
    c.execute("SELECT id FROM staff WHERE email='teacher@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute("INSERT INTO staff (staff_id,first_name,last_name,email,password,subject,classes_taught,role,date_employed,phone) VALUES (?,?,?,?,?,?,?,?,?,?)", ('STF-001','Nomvula','Khumalo','teacher@nyatsime.ac.zw',hash_pw('teacher123'),'Mathematics','Form 3A, Form 4B','Teacher','2024-01-15','0771234567'))
    c.execute("SELECT id FROM staff WHERE email='admin@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute("INSERT INTO staff (staff_id,first_name,last_name,email,password,subject,classes_taught,role,date_employed) VALUES (?,?,?,?,?,?,?,?,?)", ('STF-002','Admin','User','admin@nyatsime.ac.zw',hash_pw('admin123'),'Administration','All','Admin','2024-01-01'))
    c.execute("SELECT id FROM learners WHERE email='learner@nyatsime.ac.zw'")
    if not c.fetchone():
        c.execute("INSERT INTO learners (learner_id,first_name,last_name,email,password,grade,gender,phone) VALUES (?,?,?,?,?,?,?,?)", ('LRN-001','Amahle','Dlamini','learner@nyatsime.ac.zw',hash_pw('learner123'),'Form 3A','Female','0771112222'))
    c.execute("SELECT id FROM marks WHERE learner_id='LRN-001'")
    if not c.fetchone():
        c.executemany("INSERT INTO marks (learner_id,staff_id,subject,assessment_type,grade,score,max_score,comment) VALUES (?,?,?,?,?,?,?,?)",[
            ('LRN-001','STF-001','Mathematics','Test 1','Form 3A',78,100,'Good work!'),
            ('LRN-001','STF-001','Mathematics','Test 2','Form 3A',85,100,'Excellent!'),
            ('LRN-001','STF-001','Mathematics','Assignment 1','Form 3A',92,100,'Outstanding!'),
        ])
    conn.commit(); conn.close()

def send_json(h, data, code=200):
    body = json.dumps(data).encode()
    h.send_response(code)
    h.send_header('Content-Type','application/json')
    h.send_header('Content-Length',str(len(body)))
    h.send_header('Access-Control-Allow-Origin','*')
    h.end_headers()
    h.wfile.write(body)

def read_body(h):
    length = int(h.headers.get('Content-Length',0))
    return json.loads(h.rfile.read(length)) if length else {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin','*')
        self.send_header('Access-Control-Allow-Methods','GET,POST,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if p == '/' or p == '/index.html':
            try:
                html = open(HTML_FILE,'rb').read()
            except:
                html = b'<h1>index.html not found</h1>'
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(html)))
            self.end_headers()
            self.wfile.write(html); return
        if p == '/api/stats':
            conn = get_db()
            send_json(self,{'total_learners':conn.execute('SELECT COUNT(*) FROM learners').fetchone()[0],'total_staff':conn.execute('SELECT COUNT(*) FROM staff').fetchone()[0],'total_marks':conn.execute('SELECT COUNT(*) FROM marks').fetchone()[0],'total_books':conn.execute('SELECT COUNT(*) FROM textbooks').fetchone()[0]})
            conn.close(); return
        if p == '/api/marks':
            lid = qs.get('learner_id',[''])[0]
            conn = get_db()
            q = 'SELECT m.*,s.first_name||" "||s.last_name AS teacher_name FROM marks m LEFT JOIN staff s ON m.staff_id=s.staff_id WHERE 1=1'
            params = []
            if lid: q+=' AND m.learner_id=?'; params.append(lid)
            q+=' ORDER BY m.date_entered DESC'
            send_json(self,[dict(r) for r in conn.execute(q,params).fetchall()])
            conn.close(); return
        if p == '/api/learners':
            conn = get_db()
            send_json(self,[dict(r) for r in conn.execute('SELECT learner_id,first_name,last_name,email,grade,gender,phone FROM learners').fetchall()])
            conn.close(); return
        m = re.match(r'^/api/learners/(.+)$',p)
        if m:
            conn = get_db()
            r = conn.execute('SELECT * FROM learners WHERE learner_id=?',(m.group(1),)).fetchone()
            conn.close()
            if r:
                d=dict(r); d.pop('password',None); send_json(self,d)
            else: send_json(self,{'error':'Not found'},404)
            return
        if p == '/api/staff':
            conn = get_db()
            send_json(self,[dict(r) for r in conn.execute('SELECT staff_id,first_name,last_name,email,subject,classes_taught,role,phone FROM staff').fetchall()])
            conn.close(); return
        if p == '/api/textbooks':
            conn = get_db()
            send_json(self,[dict(r) for r in conn.execute('SELECT * FROM textbooks').fetchall()])
            conn.close(); return
        self.send_response(404); self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        body = read_body(self)
        if p == '/api/staff/login':
            conn = get_db()
            s = conn.execute('SELECT * FROM staff WHERE email=? AND password=?',(body.get('email',''),hash_pw(body.get('password','')))).fetchone()
            conn.close()
            if s: send_json(self,{'success':True,'user':{'id':s['staff_id'],'name':f"{s['first_name']} {s['last_name']}",'email':s['email'],'subject':s['subject'],'classes':s['classes_taught'],'role':s['role']}})
            else: send_json(self,{'success':False,'message':'Invalid email or password.'},401)
            return
        if p == '/api/learner/login':
            conn = get_db()
            l = conn.execute('SELECT * FROM learners WHERE email=? AND password=?',(body.get('email',''),hash_pw(body.get('password','')))).fetchone()
            conn.close()
            if l: send_json(self,{'success':True,'user':{'id':l['learner_id'],'name':f"{l['first_name']} {l['last_name']}",'email':l['email'],'grade':l['grade'],'gender':l['gender']}})
            else: send_json(self,{'success':False,'message':'Invalid email or password.'},401)
            return
        if p == '/api/learner/register':
            conn = get_db()
            try:
                count = conn.execute('SELECT COUNT(*) FROM learners').fetchone()[0]
                lid = f"LRN-{str(count+1).zfill(3)}"
                conn.execute('INSERT INTO learners (learner_id,first_name,last_name,email,password,grade,gender,phone,address,id_number,date_of_birth,next_of_kin_name,next_of_kin_relationship,next_of_kin_phone,next_of_kin_email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(lid,body.get('first_name',''),body.get('last_name',''),body.get('email',''),hash_pw(body.get('password','')),body.get('grade',''),body.get('gender',''),body.get('phone',''),body.get('address',''),body.get('id_number',''),body.get('date_of_birth',''),body.get('next_of_kin_name',''),body.get('next_of_kin_relationship',''),body.get('next_of_kin_phone',''),body.get('next_of_kin_email','')))
                conn.commit(); conn.close()
                send_json(self,{'success':True,'learner_id':lid})
            except Exception as e:
                conn.close(); send_json(self,{'success':False,'message':str(e)},400)
            return
        if p == '/api/marks':
            conn = get_db()
            try:
                conn.execute('INSERT INTO marks (learner_id,staff_id,subject,assessment_type,grade,score,max_score,comment) VALUES (?,?,?,?,?,?,?,?)',(body['learner_id'],body['staff_id'],body['subject'],body['assessment_type'],body.get('grade',''),body['score'],body['max_score'],body.get('comment','')))
                conn.commit(); conn.close(); send_json(self,{'success':True})
            except Exception as e:
                conn.close(); send_json(self,{'success':False,'message':str(e)},400)
            return
        if p == '/api/textbooks':
            conn = get_db()
            try:
                count = conn.execute('SELECT COUNT(*) FROM textbooks').fetchone()[0]
                bid = f"BK-{str(count+1).zfill(3)}"
                conn.execute('INSERT INTO textbooks (book_id,title,subject,grade_level,author,publisher,isbn,edition,total_copies,condition_notes) VALUES (?,?,?,?,?,?,?,?,?,?)',(bid,body['title'],body.get('subject',''),body.get('grade_level',''),body.get('author',''),body.get('publisher',''),body.get('isbn',''),body.get('edition',''),body.get('total_copies',0),body.get('condition_notes','')))
                conn.commit(); conn.close(); send_json(self,{'success':True,'book_id':bid})
            except Exception as e:
                conn.close(); send_json(self,{'success':False,'message':str(e)},400)
            return
        if p == '/api/logout':
            send_json(self,{'success':True}); return
        self.send_response(404); self.end_headers()

    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r'^/api/marks/(\d+)$',p)
        if m:
            conn = get_db()
            conn.execute('DELETE FROM marks WHERE id=?',(int(m.group(1)),))
            conn.commit(); conn.close()
            send_json(self,{'success':True}); return
        self.send_response(404); self.end_headers()

if __name__ == '__main__':
    init_db()
    server = HTTPServer(('0.0.0.0',PORT),Handler)
    print(f"Server running on port {PORT}")
    server.serve_forever()
