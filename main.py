#!/usr/bin/env python3

import argparse, base64, getpass, os, subprocess, sqlite3
import threading, time
import flask, scrypt
import Config

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "start"}

HEADINGS= ["ID", "Name", "Status", "Percent", "Size", "Ratio"]
ARROW_DOWN = "▾"
ARROW_UP = "▴"

app = flask.Flask(__name__)
app.config.from_object(Config)

def get_database():
	if not hasattr(flask.g, "databases"):
		flask.g.databases = {}
	id = threading.current_thread().ident
	if not id in flask.g.databases:
		flask.g.databases[id] = sqlite3.connect("btpd-web.db")
	return flask.g.databases[id]
def get_cursor():
	if not hasattr(flask.g, "cursors"):
		flask.g.cursors = {}
		make_table()
	id = threading.current_thread().ident
	if not id in flask.g.cursors:
		flask.g.cursors[id] = get_database().cursor()
	return flask.g.cursors[id]

def make_table():
	try:
		get_cursor().execute("""CREATE TABLE users (username text,
			session text, hash text, salt text)""")
	except sqlite3.OperationalError:
		pass

def make_hash(password, salt):
	return base64.b64encode(scrypt.hash(password, salt))
def make_salt():
	return base64.b64encode(os.urandom(32)).decode("utf8")
def authenticate(username, password):
	get_cursor().execute(
		"SELECT hash, salt FROM users WHERE username=?", [
		username])
	hash, salt = get_cursor().fetchone() or [None, None]
	if hash and hash == make_hash(password, salt).decode("utf8"):
		return True
	return False
def is_authenticated():
	if flask.request.cookies.get("btpd-session"):
		get_cursor().execute(
			"SELECT username FROM users WHERE session=?",
			[flask.request.cookies["btpd-session"]])
		username = get_cursor().fetchone()
		if username:
			return True
	return False
def make_session():
	return base64.b64encode(os.urandom(32)).decode("utf8")
def set_session(username, session):
	get_cursor().execute(
		"UPDATE users SET session=? WHERE username=?",
		[session, username])
	get_database().commit()
def add_user(username, password, salt):
	get_cursor().execute("""INSERT INTO USERS (username, password,
		salt) VALUES (?, ?, ?)""", [username, password, salt])
	get_database.commit()

def get_referrer_params():
	if flask.request.referrer:
		referrer_params = flask.request.referrer.split("?", 1)
		if len(referrer_params) > 1:
			return "?%s" % referrer_params[1]
	return ""

@app.route("/")
def index():
	if not is_authenticated():
		return flask.redirect(flask.url_for("login"))
	referrer_params = get_referrer_params()
	orderby = flask.request.args.get("orderby")
	descending = True
	headings = HEADINGS[:]
	if orderby and orderby.startswith("-"):
		descending = False
		orderby = orderby[1:]
	lines = subprocess.check_output(["btcli", "list", "-f", "%n %# %t %p %S %r %s\\n"]
		).decode("utf8").strip().split("\n")
	if not orderby or not orderby.isdigit() or int(orderby) >= len(lines)-1:
		orderby = 0
	else:
		orderby = int(orderby)
	arrow = ARROW_DOWN if descending else ARROW_UP
	headings[orderby] = "%s %s" % (headings[orderby], arrow)
	parsed_lines = []
	failed = False
	if lines[0].startswith("cannot open connection"):
		failed = True
	else:
		for line in lines[1:]:
			line = line.rsplit(None, 6)
			line.insert(0, int(line.pop(1)))
			line.insert(3, float(line.pop(3)[:-1]))
			line.insert(4, int(line.pop(4)))
			line.insert(5, float(line.pop(5)))
			if line[2] in TORRENT_STATES:
				line[2] = TORRENT_STATES[line[2]]
			parsed_lines.append(line)
	orders = ["%s%d" % ("-" if n == orderby and descending else "", n) for n in range(6)]
	parsed_lines = sorted(parsed_lines, key=lambda l: l[orderby], reverse=descending)
	for n, line in enumerate(parsed_lines):
		line[3] = "%.1f" % line[3]
		line[4] = line.pop(6)
		line[5] = "%.2f" % line[5]
		parsed_lines[n] = line
	return flask.render_template("index.html", failed=failed,
		lines=parsed_lines, orders=orders, fragment="list.html",
		headings=headings)

@app.route("/action")
def torrent_action():
	referrer_params = get_referrer_params()
	if not is_authenticated():
		return flask.redirect(flask.url_for("login"))
	state = flask.request.args["state"]
	id = flask.request.args["id"]
	if not id.isdigit() or not state in TORRENT_ACTIONS:
		return flask.abort(400)
	out = subprocess.check_output(["btcli", TORRENT_ACTIONS[state], id],
		stderr=subprocess.STDOUT)
	if not flask.request.is_xhr:
		return flask.redirect("%s%s" % (flask.url_for("index"), referrer_params))
	return "0" if out else "1"

@app.route("/add", methods=["GET", "POST"])
def add():
	if not is_authenticated():
		return flask.redirect(flask.url_for("login"))
	failed = False
	if flask.request.method == "POST":
		directory = flask.request.form["directory"]
		file = flask.request.files["file"]
		file.save("/tmp/torrent")
		subprocess.check_call(["btcli", "add", "-d",
			os.path.join(app.config["BASEDIR"], directory),
			"/tmp/torrent"])
		return flask.redirect(flask.url_for("index"))
	return flask.render_template("index.html",
		fragment="add.html")
@app.route("/remove")
def remove():
	if not is_authenticated():
		return flask.redirect(flask.url_for("login"))
	id = flask.request.args["id"]
	if "seriously" in flask.request.args:
		if flask.request.args["seriously"] == "1":
			subprocess.check_call(["btcli", "del", id])
		return flask.redirect(flask.url_for("index"))
	else:
		title = subprocess.check_output(["btcli", "list", id,
			"--format", "%n"]).decode("latin-1")
		return flask.render_template("index.html", id=id,
			fragment="seriously.html",title=title,
			warning="Are you sure you want to remove this torrent?")

@app.route("/login", methods=["GET", "POST"])
def login():
	if flask.request.method == "GET":
		if is_authenticated():
			return flask.redirect(flask.url_for("index"))
		return flask.render_template("index.html",
			fragment="login.html", loginfailed=False)
	elif flask.request.method == "POST":
		username = flask.request.form["username"]
		password = flask.request.form["password"]
		if authenticate(username, password):
			session = make_session()
			set_session(username, session)
			response = flask.make_response(
				flask.redirect(flask.url_for(
				"index")))
			response.set_cookie("btpd-session", session)
			return response
		else:
			return flask.render_template("index.html",
				fragment="login.html",
				loginfailed=True)
if __name__ == "__main__":
	bindhost = app.config.get("BINDHOST", "127.0.0.1")
	port = app.config.get("PORT", 5000)
	debug = app.config.get("DEBUG", False)
	app.run(host=bindhost, port=port, debug=debug)
