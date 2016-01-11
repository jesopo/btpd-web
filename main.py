#!/usr/bin/env python3

import argparse, base64, codecs, hashlib, os, subprocess
import sqlite3, threading, time
import flask, scrypt, libtorrent, werkzeug
import Config, Database
import bencode

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "stop", "starting": "stop"}

HEADINGS= ["ID", "Name", "Status", "Percent", "Size", "Ratio"]
ARROW_DOWN = "▾"
ARROW_UP = "▴"

USERS_ACTIONS = ["delete", "add"]

app = flask.Flask(__name__)
app.config.from_object(Config)

database = Database.Database()

def is_authenticated():
	with database:
		return database.is_authenticated(
			flask.request.cookies.get(
			"btpd-session"))
def is_admin():
	with database:
		return database.is_admin(flask.request.cookies[
			"btpd-session"])
def login_redirect():
	return flask.redirect(flask.url_for("login"))
def get_referrer_params():
	if flask.request.referrer:
		referrer_params = flask.request.referrer.split("?", 1)
		if len(referrer_params) > 1:
			return "?%s" % referrer_params[1]
	return ""
def make_page(fragment, **kwargs):
	username = None
	admin = False
	session = flask.request.cookies.get("btpd-session")
	with database:
		username = database.username_from_session(session)
		admin = database.is_admin(session)
	return flask.render_template("index.html", fragment=fragment,
		username=username, admin=admin, **kwargs)
@app.route("/")
def index():
	if not is_authenticated():
		return login_redirect()
	referrer_params = get_referrer_params()
	orderby = flask.request.args.get("orderby", "0")
	descending = True
	headings = HEADINGS[:]
	if orderby and orderby.startswith("-"):
		descending = False
		orderby = orderby[1:]
	lines = subprocess.check_output([
	        "btcli", "list", "-f", "%n %# %t %p %S %r %s %h\\n"]
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
			line = line.rsplit(None, 7)
			line.insert(0, int(line.pop(1)))
			line.insert(3, float(line.pop(3)[:-1]))
			line.insert(4, int(line.pop(4)))
			line.insert(5, float(line.pop(5)))
			if line[2] in TORRENT_STATES:
				line[2] = TORRENT_STATES[line[2]]
			parsed_lines.append(line)
	orders = ["%s%d" % ("-" if n == orderby and descending else "", n) for n in range(6)]
	parsed_lines = sorted(parsed_lines, key=lambda l: l[orderby], reverse=descending)

	page = int(flask.request.args.get("page", 1))-1
	next_page = page+1
	pages = int(len(parsed_lines)/app.config["PER_PAGE"])
	if len(parsed_lines)%app.config["PER_PAGE"] > 0:
		pages += 1
	parsed_lines = parsed_lines[app.config["PER_PAGE"
		]*page:app.config["PER_PAGE"]*next_page]

	for n, line in enumerate(parsed_lines):
		line[3] = "%.1f" % line[3]
		line[4] = line.pop(6)
		line[5] = "%.2f" % line[5]
		parsed_lines[n] = line
	return make_page("list.html", failed=failed, lines=parsed_lines,
		orders=orders, headings=headings, pages=pages, page=page,
		orderby=orderby)

@app.route("/action")
def torrent_action():
	if not is_authenticated():
		return login_redirect()
	referrer_params = get_referrer_params()
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
		return login_redirect()
	failed = False
	if flask.request.method == "POST":
		directory = flask.request.form["directory"]
		if directory.startswith("/"):
			directory = directory[1:]
		if "../" in directory:
			return flask.abort(400)
		filename = "/tmp/btpd.%d." % os.getpid()
		if flask.request.form["url"].strip():
			filename = "%surl.%s.torrent" % (filename,
				hashlib.md5(flask.request.form[
				"url"].encode("utf8")).hexdigest())
			subprocess.check_call(["wget", "-O",
				filename, flask.request.form[
				"url"]])
		else:
			file = flask.request.files["file"]
			filename = "%sfile.%s.torrent" % (filename,
				hashlib.md5(file.read()
				).hexdigest())
			file.save(filename)

		torrent = libtorrent.bdecode(open(filename, "rb"
			).read())
		info_hash = codecs.encode(libtorrent.torrent_info(torrent
			).info_hash().to_bytes(), "hex")

		idle = "idle" in flask.request.form
		add_command = ["btcli", "add", "-d",
			os.path.join(app.config["BASEDIR"], directory),
			filename]
		if idle:
			add_command.append("-N")
		subprocess.check_call(add_command)
		os.remove(filename)
		with database:
			username = database.username_from_session(
				flask.request.cookies["btpd-session"])
			database.add_torrent(info_hash, username)
		return flask.redirect(flask.url_for("index"))
	return make_page("add.html")
@app.route("/remove")
def remove():
	if not is_authenticated():
		return login_redirect()
	id = flask.request.args["id"]
	if "seriously" in flask.request.args:
		if flask.request.args["seriously"] == "1":
			subprocess.check_call(["btcli", "del", id])
		return flask.redirect(flask.url_for("index"))
	else:
		title = subprocess.check_output(["btcli", "list", id,
			"--format", "%n"]).decode("latin-1")
		return make_page("seriously.html", id=id, title=title,
			warning="Are you sure you want to remove this torrent?")

@app.route("/login", methods=["GET", "POST"])
def login():
	if is_authenticated():
		return flask.redirect(flask.url_for("index"))
	if flask.request.method == "GET":
		return make_page("login.html", loginfailed=False)
	elif flask.request.method == "POST":
		username = flask.request.form["username"]
		password = flask.request.form["password"]
		with database:
			if database.authenticate(username, password):
				session = database.make_session()
				database.add_session(username, session)
				response = flask.make_response(
					flask.redirect(flask.url_for(
					"index")))
				response.set_cookie("btpd-session",
					session)
				return response
			else:
				return make_page("login.html",
					loginfailed=True)
@app.route("/logout")
def logout():
	if is_authenticated():
		with database:
			database.del_session(flask.request.cookies[
				"btpd-session"])
	return login_redirect()
@app.route("/settings")
def settings():
	if not is_authenticated():
		return login_redirect()
	return make_page("settings.html")
@app.route("/users", methods=["GET", "POST"])
def users():
	if not is_admin():
		return flask.abort(400)
	if "action" in flask.request.args:
		if not flask.request.method == "POST":
			return flask.abort(400)
		action = flask.request.args["action"].lower()
		if not action in USERS_ACTIONS:
			return flask.abort(400)
		if action == "add":
			if not "username" in flask.request.args:
				return make_page("adduser.html")
			else:
				username = flask.form.args["username"]
				password = flask.form.args["password"]
				admin = admin in flask.request.form
				with database:
					database.add_user(username,
						password, admin)
				return flask.redirect(flask.url_for(
					"users"))
		elif action == "delete":
			id = flask.request.args["id"]
			if "seriously" in flask.request.args:
				if flask.request.args["seriously"] == "1":
					with database:
						database.del_user(id)
					return flask.redirect(
						flask.url_for("users"))
			else:
				with database:
					username = database.username_from_id(
						id)
				return make_page("userdelete.html",
					id=id, username=username)
	with database:
		users = database.list_users()
	for i, user in enumerate(users):
		user = list(user)
		user[2] = bool(user[2])
		users[i] = user
	return make_page("users.html", users=users)
if __name__ == "__main__":
	bindhost = app.config.get("BINDHOST", "127.0.0.1")
	port = app.config.get("PORT", 5000)
	debug = app.config.get("DEBUG", False)
	app.run(host=bindhost, port=port, debug=debug)
