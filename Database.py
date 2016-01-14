import base64, os, sqlite3, threading
import scrypt

class Database(object):
	def __init__(self):
		self.lock = threading.RLock()
		self.database = None
		self.cursor = None
		self.location = "btpd-web.db"
		with self:
			self.make_users_table()
			self.make_sessions_table()
			self.make_torrents_table()
			if not self.has_username("root"):
				password = base64.b64encode(
					os.urandom(16)).decode("utf8")
				self.add_user("root", password, True)
				print("added root user.")
				print("password: %s" % password)
	def __enter__(self):
		self.lock.acquire()
		self.database = sqlite3.connect(self.location)
		self.database.isolation_level = None
		self.cursor = self.database.cursor()
		self.cursor.execute("PRAGMA foreign_keys=ON")
	def __exit__(self, type, value, traceback):
		if self.database:
			self.database.close()
			self.database = None
			self.cursor = None
		self.lock.release()
	def make_users_table(self):
		try:
			self.cursor.execute("""CREATE TABLE users (
				id INTEGER PRIMARY KEY, username text
				UNIQUE, hash text, salt text, admin
				bool)""")
		except sqlite3.OperationalError:
			pass
	def make_sessions_table(self):
		try:
			self.cursor.execute("""CREATE TABLE sessions (
				id int, session text UNIQUE, FOREIGN
				KEY(id) REFERENCES users(id) ON DELETE
				CASCADE)""")
		except sqlite3.OperationalError:
			pass
	def make_torrents_table(self):
		try:
			self.cursor.execute("""CREATE TABLE torrents (
				info_hash text PRIMARY KEY, id int,
				FOREIGN KEY(id) REFERENCES users(id)
				ON DELETE CASCADE)""")
		except sqlite3.OperationalError:
			pass
	def make_salt(self):
		return base64.b64encode(os.urandom(32)).decode("utf8")
	def make_session(self):
		return base64.b64encode(os.urandom(32)).decode("utf8")
	def make_hash(self, password, salt):
		return base64.b64encode(scrypt.hash(password, salt)
			).decode("utf8")
	def get_user_id(self, username):
		self.cursor.execute(
			"SELECT id FROM users WHERE username=?",
			[username])
		return (self.cursor.fetchone() or [None])[0]
	def add_session(self, username, session):
		id = self.get_user_id(username)
		if id:
			self.cursor.execute("""INSERT INTO sessions (
				id, session) VALUES (?, ?)""",
				[id, session])
	def del_session(self, session):
		self.cursor.execute(
			"DELETE FROM sessions WHERE session=?",
			[session])
	def authenticate(self, username, password):
		self.cursor.execute(
			"SELECT hash, salt FROM users WHERE username=?",
			[username])
		hash, salt = self.cursor.fetchone() or [None, None]
		hashed = self.make_hash(password, salt)
		if hash and hash == self.make_hash(password, salt):
			return True
		return False
	def is_authenticated(self, session):
		id = self.id_from_session(session)
		return bool(id)
	def add_user(self, username, password, admin=False):
		salt = self.make_salt()
		hash = self.make_hash(password, salt)
		self.cursor.execute("""INSERT INTO users (id,
			username, hash, salt, admin) VALUES (?, ?, ?,
			?, ?)""", [None, username, hash, salt, admin])
	def del_user(self, id):
		assert id != 1
		self.cursor.execute(
			"DELETE FROM users WHERE id=?", [id])
	def user_count(self):
		self.cursor.execute(
			"SELECT COUNT(*) FROM users")
		return self.cursor.fetchone()[0]
	def has_username(self, username):
		self.cursor.execute(
			"SELECT 1 FROM users WHERE username=?",
			[username])
		result = self.cursor.fetchone()
		return (result or [None])[0] == 1
	def username_from_id(self, id):
		self.cursor.execute(
			"SELECT username FROM users WHERE id=?", [id])
		username = self.cursor.fetchone()
		return (username or [None])[0]
	def id_from_session(self, session):
		self.cursor.execute(
			"SELECT id FROM sessions WHERE session=?",
			[session])
		id = self.cursor.fetchone()
		return (id or [None])[0]
	def id_from_username(self, username):
		self.cursor.execute(
			"SELECT id FROM users WHERE username=?",
			[username])
		id = self.cursor.fetchone()
		return (id or [None])[0]
	def username_from_session(self, session):
		id = self.id_from_session(session)
		self.cursor.execute(
			"SELECT username FROM users WHERE id=?", [id])
		username = self.cursor.fetchone()
		return (username or [None])[0]
	def is_admin(self, session):
		id = self.id_from_session(session)
		self.cursor.execute(
			"SELECT admin FROM users WHERE id=?", [id])
		admin = self.cursor.fetchone()
		return (admin or [None])[0]
	def list_users(self):
		self.cursor.execute(
			"SELECT id, username,admin FROM users")
		users = self.cursor.fetchall()
		return users
	def add_torrent(self, info_hash, username):
		id = self.id_from_username(username)
		if id:
			self.cursor.execute("""INSERT INTO torrents (
				info_hash, id) VALUES (?, ?)""",
				[info_hash, id])
	def get_torrent_owner(self, info_hash):
		self.cursor.execute(
			"SELECT id FROM torrents WHERE info_hash=?",
			[info_hash])
		id = self.cursor.fetchone()
		return (id or [None])[0]
Database()
