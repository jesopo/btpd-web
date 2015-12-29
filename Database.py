import base64, os, sqlite3
import scrypt

class Database(object):
	def __init__(self):
		self.database = None
		self.cursor = None
		self.location = "btpd-web.db"
		with self:
			self.make_users_table()
			self.make_sessions_table()
			if self.user_count() == 0:
				password = base64.b64encode(
					os.urandom(16)).decode("utf8")
				self.add_user("root", password)
				print("added root user.")
				print("password: %s" % password)
	def __enter__(self):
		self.database = sqlite3.connect(self.location)
		self.database.isolation_level = None
		self.cursor = self.database.cursor()
	def __exit__(self, type, value, traceback):
		if self.database:
			self.database.close()
			self.database = None
			self.cursor = None
	def make_users_table(self):
		try:
			self.cursor.execute("""CREATE TABLE users (
				id INTEGER PRIMARY KEY, username text
				UNIQUE, hash text, salt texxt)""")
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
		self.cursor.execute(
			"SELECT id FROM sessions WHERE session=?",
			[session])
		id = self.cursor.fetchone()
		return bool(id)
	def add_user(self, username, password):
		salt = self.make_salt()
		hash = self.make_hash(password, salt)
		self.cursor.execute("""INSERT INTO users (id,
			username, hash, salt) VALUES (?, ?, ?, ?)""",
			[None, username, hash, salt])
	def user_count(self):
		self.cursor.execute(
			"SELECT COUNT(*) FROM users")
		return self.cursor.fetchone()[0]
Database()