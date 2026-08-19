import sqlite3
from werkzeug.security import generate_password_hash

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # Added device_id for Anti-Buddy Punching
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(50) PRIMARY KEY,
            username VARCHAR(100) NOT NULL,
            password VARCHAR(255) NOT NULL,
            role VARCHAR(10) NOT NULL,
            device_id VARCHAR(255)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            sub_id VARCHAR(20) PRIMARY KEY,
            sub_name VARCHAR(100) NOT NULL,
            teacher_id VARCHAR(50),
            FOREIGN KEY (teacher_id) REFERENCES users(user_id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS attendance_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id VARCHAR(50),
            sub_id VARCHAR(20),
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(10) DEFAULT 'PRESENT',
            FOREIGN KEY (student_id) REFERENCES users(user_id),
            FOREIGN KEY (sub_id) REFERENCES subjects(sub_id)
        )
    ''')

    c.execute('DELETE FROM users')
    c.execute('DELETE FROM subjects')
    c.execute('DELETE FROM attendance_logs')

    users = [
        ('T101', 'Prof. Ramesh', generate_password_hash('teacher123'), 'teacher', None),
        ('S101', 'Deepak S.', generate_password_hash('student123'), 'student', None),
        ('S102', 'Amit Verma', generate_password_hash('student123'), 'student', None),
    ]
    c.executemany('INSERT INTO users VALUES (?, ?, ?, ?, ?)', users)

    subjects = [('CS101', 'Data Structures', 'T101'), ('DS202', 'Machine Learning', 'T101')]
    c.executemany('INSERT INTO subjects VALUES (?, ?, ?)', subjects)

    conn.commit()
    conn.close()
    print("Database V4 initialized successfully.")

if __name__ == '__main__':
    init_db()