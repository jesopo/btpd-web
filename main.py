#!/usr/bin/env python3

import copy, argparse, base64, codecs, datetime, hashlib
import os, subprocess, sqlite3, threading, time
import flask, scrypt, libtorrent, werkzeug
import Config, Database, Utils

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "stop", "starting": "stop"}

HEADINGS= ["ID", "Name", "State", "Percent", "Size", "Ratio", "Uploader"]
ARROW_DOWN = "▾"
ARROW_UP = "▴"

app = flask.Flask(__name__)
app.config.from_object(Config)

database = Database.Database()

torrent_list = {}
last_list = 0
list_lock = threading.Lock()
list_condition = threading.Condition()
def fill_torrent_list():
	while True:
		global last_list
		global torrent_list
		lines = Utils.get_torrent_list()
		torrents = {}
		for i, line in enumerate(lines):
			line = line.rsplit(None, 7)
			with database:
				owner = database.get_torrent_owner(
					line[-1])
				if not owner:
					database.add_torrent(line[-1],
						"root")
					owner = 1
				owner_username = database.username_from_id(
					owner)
			torrent = {"owner": owner, "name": line[0],
				"id": int(line[1]), "state": line[2],
				"percent": float(line[3][:-1]), "bytes":
				int(line[4]), "ratio": float(line[5]),
				"size": line[6], "info_hash": line[7],
				"uploader": owner_username}
			if torrent["state"] in TORRENT_STATES:
				torrent["state"] = TORRENT_STATES[
					torrent["state"]]
			torrents[torrent["id"]] = torrent
		removed = set(torrent["info_hash"
			] for torrent in torrent_list.values())-set(torrent[
			"info_hash"] for torrent in torrents.values())
		for info_hash in removed:
			with database:
				database.del_torrent(info_hash)
		with list_lock:
			torrent_list = torrents
		since_last = time.time()-last_list
		interval = app.config.get("LIST_INTERVAL", 4)
		if last_list == 0 or since_last < interval:
			sleep_time = interval-since_last
			if last_list == 0:
				sleep_time = interval
			with list_condition:
				list_condition.wait(sleep_time)
		last_list = time.time()
list_thread = threading.Thread(target=fill_torrent_list)
list_thread.daemon = True

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
	session = flask.request.cookies["btpd-session"]
	with database:
		admin = database.is_admin(session)
		user_id = database.id_from_session(session)
	referrer_params = get_referrer_params()
	orderby = flask.request.args.get("orderby", "0")
	descending = True
	headings = HEADINGS[:]
	if orderby and orderby.startswith("-"):
		descending = False
		orderby = orderby[1:]

	with list_lock:
		parsed_lines = copy.deepcopy(list(
			torrent_list.values()))
	if not orderby or not orderby.isdigit() or int(orderby
			) >= len(parsed_lines)-1:
		orderby = 0
	else:
		orderby = int(orderby)

	arrow = ARROW_DOWN if descending else ARROW_UP
	headings[orderby] = "%s %s" % (headings[orderby], arrow)
	for i, line in enumerate(parsed_lines):
		if not admin and not line["owner"] == user_id:
			continue
		parsed_lines[i] = line
	orders = ["%s%d" % ("-" if n == orderby and descending else "",
		n) for n in range(7)]
	if not orderby == 0:
		parsed_lines = sorted(parsed_lines,
			key=lambda l: l[HEADINGS[0].lower()],
			reverse=descending)
	parsed_lines = sorted(parsed_lines, key=lambda l: l[HEADINGS[
		orderby].lower()].title(), reverse=descending)

	page = int(flask.request.args.get("page", 1))-1
	next_page = page+1
	pages = int(len(parsed_lines)/app.config["PER_PAGE"])
	if len(parsed_lines)%app.config["PER_PAGE"] > 0:
		pages += 1
	parsed_lines = parsed_lines[app.config["PER_PAGE"
		]*page:app.config["PER_PAGE"]*next_page]

	for n, line in enumerate(parsed_lines):
		line["percent"] = "%.1f%%" % line["percent"]
		line["ratio"] = "%.2f" % line["ratio"]
		parsed_lines[n] = line
	return make_page("list.html", lines=parsed_lines, orders=orders,
		headings=headings, pages=pages, page=page, orderby=orderby)

@app.route("/action")
def torrent_action():
	if not is_authenticated():
		return login_redirect()
	referrer_params = get_referrer_params()
	state = flask.request.args["state"]
	id = flask.request.args["id"]
	if not id.isdigit() or not state in TORRENT_ACTIONS:
		return flask.abort(400)
	Utils.do_torrent_action(id, TORRENT_ACTIONS[state])
	with list_condition:
		list_condition.notify()
	return flask.redirect("%s%s" % (flask.url_for("index"),
		referrer_params))

@app.route("/add", methods=["GET", "POST"])
def add():
	if not is_authenticated():
		return login_redirect()
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
			).info_hash().to_bytes(), "hex").decode("utf8")

		idle = "idle" in flask.request.form
		directory = os.path.join(app.config["BASEDIR"], directory)

		Utils.add_torrent(directory, filename, idle)
		os.remove(filename)
		with list_condition:
			list_condition.notify()

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
		with list_lock:
			info_hash = torrent_list[int(id)]["info_hash"]
		if flask.request.args["seriously"] == "1":
			with database:
				database.del_torrent(info_hash)
			Utils.remove_torrent(id)
		with list_condition:
			list_condition.notify()
		return flask.redirect(flask.url_for("index"))
	else:
		with list_lock:
			title = torrent_list[int(id)]["name"]
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
				expiration = datetime.datetime.now()
				expiration += datetime.timedelta(
					days=90)
				response.set_cookie("btpd-session",
					session, expires=expiration)
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

@app.route("/users")
def users():
	if not is_admin():
		return login_redirect()
	with database:
		users = database.list_users()
	for i, user in enumerate(users):
		user = list(user)
		user[2] = "✓" if user[2] == 1 else "✘"
		users[i] = user
	return make_page("users.html", users=users)

@app.route("/adduser", methods=["GET", "POST"])
def add_user():
	if not is_admin():
		return login_redirect()
	if flask.request.method == "POST":
		username = flask.request.form["username"]
		password = flask.request.form["password"]
		password_confirm = flask.request.form["passwordconfirm"]
		admin = "admin" in flask.request.form
		if not password == password_confirm:
			return make_page("adduser.html",
				usernamefield=username,
				adduserfailed=True)
		with database:
			database.add_user(username, password, admin)
		return flask.redirect(flask.url_for("users"))
	else:
		return make_page("adduser.html")

@app.route("/removeuser")
def remove_user():
	if not is_admin():
		return login_redirect()
	id = flask.request.args["id"]
	if "seriously" in flask.request.args:
		if flask.request.args["seriously"] == "1":
			with database:
				database.del_user(id)
		return flask.redirect(flask.url_for(
			"users"))
	else:
		with database:
			username = database.username_from_id(id)
		return make_page("userseriously.html",
			id=id, target_username=username,
			warning="Are you sure you want to remove"
			"this user?")

if __name__ == "__main__":
	list_thread.start()
	bindhost = app.config.get("BINDHOST", "127.0.0.1")
	port = app.config.get("PORT", 5000)
	debug = app.config.get("DEBUG", False)
	app.run(host=bindhost, port=port, debug=debug)
