"""Initialize FormGuard AI SQLite database and default admin user."""
from database import init_db, get_db_connection, DB_PATH, seed_demo_documents
from werkzeug.security import generate_password_hash

init_db()
admin_password = generate_password_hash('admin123')
conn = get_db_connection()
conn.execute(
    "INSERT OR IGNORE INTO users (id, name, email, password, role, created_at) VALUES (1, ?, ?, ?, ?, datetime('now'))",
    ('Administrator', 'admin@formguard.ai', admin_password, 'admin'),
)
conn.commit()
conn.close()

# Seed realistic sample files in uploads/ + database (citizenship, ID, marksheet, etc.)
try:
    from seed_sample_uploads import seed_for_user
    seed_for_user(1, replace=False)
except Exception as e:
    print('Sample uploads seed skipped:', e)
    seed_demo_documents(user_id=1, min_docs=12)

print('Database ready at', DB_PATH)
print('Admin login: admin@formguard.ai / admin123')
