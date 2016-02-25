import base64, json, os, sqlite3, threading
import scrypt

class Database(object):
	def __init__(self):
		self.location = "btpd-web.db"
		self.database = sqlite3.connect(self.location,
			isolation_level=None, check_same_thread=False)
		self.cursors = {}
		self.make_users_table()
		self.make_settings_table()
		self.make_sessions_table()
		self.make_torrents_table()
		if not self.has_username("root"):
			password = base64.b64encode(
				os.urandom(16)).decode("utf8")
			self.add_user("root", password, True)
			print("added root user.")
			print("password: %s" % password)
	def cursor(self):
		id = threading.current_thread().ident
		if not id in self.cursors:
			self.cursors[id] = self.database.cursor()
			self.cursors[id].execute(
				"PRAGMA foreign_keys=ON")
		return self.cursors[id]
	def make_users_table(self):
		try:
			self.cursor().execute("""CREATE TABLE users (
				id INTEGER PRIMARY KEY, username text
				UNIQUE, hash text, salt text, admin
				bool)""")
		except sqlite3.OperationalError:
			pass
	def make_settings_table(self):
		try:
			self.cursor().execute("""CREATE TABLE settings (
				user_id INTEGER, setting TEXT, value TEXT,
				PRIMARY KEY (user_id, setting), FOREIGN
				KEY(user_id) REFERENCES users(id) ON DELETE
				CASCADE)""")
		except sqlite3.OperationalError:
			pass
	def make_sessions_table(self):
		try:
			self.cursor().execute("""CREATE TABLE sessions (
				user_id INTEGER, session TEXT UNIQUE, FOREIGN
				KEY(user_id) REFERENCES users(id) ON DELETE
				CASCADE)""")
		except sqlite3.OperationalError:
			pass
	def make_torrents_table(self):
		try:
			self.cursor().execute("""CREATE TABLE torrents (
				info_hash TEXT PRIMARY KEY, user_id INTEGER,
				FOREIGN KEY(user_id) REFERENCES users(id)
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
		self.cursor().execute(
			"SELECT id FROM users WHERE username=?",
			[username])
		return (self.cursor().fetchone() or [None])[0]
	def add_session(self, username, session):
		id = self.get_user_id(username)
		if id:
			self.cursor().execute("""INSERT INTO sessions (
				user_id, session) VALUES (?, ?)""",
				[id, session])
	def del_session(self, session):
		self.cursor().execute(
			"DELETE FROM sessions WHERE session=?",
			[session])
	def authenticate(self, username, password):
		self.cursor().execute(
			"SELECT hash, salt FROM users WHERE username=?",
			[username])
		hash, salt = self.cursor().fetchone() or [None, None]
		if hash and salt:
			hashed = self.make_hash(password, salt)
			if hash and hash == self.make_hash(
					password, salt):
				return True
		return False
	def is_authenticated(self, session):
		id = self.id_from_session(session)
		return bool(id)
	def add_user(self, username, password, admin=False):
		salt = self.make_salt()
		hash = self.make_hash(password, salt)
		self.cursor().execute("""INSERT INTO users (id,
			username, hash, salt, admin) VALUES (?, ?, ?,
			?, ?)""", [None, username, hash, salt, admin])
	def del_user(self, id):
		assert id != 1
		self.cursor().execute(
			"DELETE FROM users WHERE id=?", [id])
	def set_password(self, username, new_password):
		salt = self.make_salt()
		hash = self.make_hash(new_password, salt)
		id = self.id_from_username(username)
		self.cursor().execute("""UPDATE users SET hash=?,salt=?
			WHERE id=?""", [hash, salt, id])
	def change_username(self, old_username, new_username):
		id = self.username_from_id(old_username)
		self.cursor().execute("""UPDATE users SET username=?
			WHERE id=?""", [new_username, id])
	def user_count(self):
		self.cursor().execute(
			"SELECT COUNT(*) FROM users")
		return self.cursor().fetchone()[0]
	def has_username(self, username):
		self.cursor().execute(
			"SELECT 1 FROM users WHERE UPPER(username)=?",
			[username.upper()])
		result = self.cursor().fetchone()
		return (result or [None])[0] == 1
	def username_from_id(self, id):
		self.cursor().execute(
			"SELECT username FROM users WHERE id=?", [id])
		username = self.cursor().fetchone()
		return (username or [None])[0]
	def id_from_session(self, session):
		self.cursor().execute(
			"SELECT user_id FROM sessions WHERE session=?",
			[session])
		id = self.cursor().fetchone()
		return (id or [None])[0]
	def id_from_username(self, username):
		self.cursor().execute("""SELECT id FROM users
			WHERE username=? COLLATE NOCASE""", [username])
		id = self.cursor().fetchone()
		return (id or [None])[0]
	def username_from_session(self, session):
		id = self.id_from_session(session)
		self.cursor().execute(
			"SELECT username FROM users WHERE id=?", [id])
		username = self.cursor().fetchone()
		return (username or [None])[0]
	def is_admin(self, session):
		id = self.id_from_session(session)
		self.cursor().execute(
			"SELECT admin FROM users WHERE id=?", [id])
		admin = self.cursor().fetchone()
		return (admin or [None])[0]
	def list_users(self):
		self.cursor().execute(
			"SELECT id, username, admin FROM users")
		users = self.cursor().fetchall()
		return users
	def add_torrent(self, info_hash, username):
		id = self.id_from_username(username)
		if id:
			self.cursor().execute("""INSERT INTO torrents (
				info_hash, user_id) VALUES (?, ?)""",
				[info_hash, id])
	def del_torrent(self, info_hash):
		self.cursor().execute(
			"DELETE FROM torrents WHERE info_hash=?",
			[info_hash])
	def get_torrent_owner(self, info_hash):
		self.cursor().execute(
			"SELECT user_id FROM torrents WHERE info_hash=?",
			[info_hash])
		id = self.cursor().fetchone()
		return (id or [None])[0]
	def torrent_count(self, id=None):
		command = "SELECT COUNT(*) FROM torrents"
		args = []
		if id:
			command += " WHERE user_id=?"
			args = [id]
		self.cursor().execute(command, args)
		count = self.cursor().fetchone()
		return (count or [0])[0]
	def get_setting(self, username, setting):
		id = self.id_from_username(username)
		self.cursor().execute("""SELECT value FROM settings
			WHERE user_id=? AND setting=?""", [id,
			setting.lower()])
		value = (self.cursor().fetchone() or [None])[0]
		if value:
			return json.loads(value)
		return None
	def get_all_settings(self, username):
		id = self.id_from_username(username)
		self.cursor().execute("""SELECT setting, value FROM
			settings WHERE user_id=?""", [id])
		settings = {}
		settings_tuples = self.cursor().fetchall()
		for setting, value in (settings_tuples or []):
			settings[setting.lower()] = json.loads(value)
		return settings
	def set_setting(self, username, setting, value):
		id = self.id_from_username(username)
		self.cursor().execute("""INSERT OR REPLACE INTO
			settings (user_id, setting, value) VALUES
			(?, ?, ?)""", [id, setting.lower(),
			json.dumps(value)])
	def has_setting(self, username, setting):
		id = self.id_from_username(username)
		self.cursor().execute("""SELECT 1 FROM settings
			WHERE user_id=? AND setting=?""", [id,
			setting.lower()])
		return (self.cursor().fetchone() or [None])[0] == 1
