#!/usr/bin/env python3

import copy, argparse, base64, codecs, datetime, hashlib
import os, subprocess, sqlite3, threading, time
import flask, scrypt, libtorrent, werkzeug
import Config, Database, Utils

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "stop", "starting": "stop"}

HEADINGS = ["ID", "Name", "State", "Percent", "Size", "Ratio", "Uploader"]
ARROW_DOWN = "▾"
ARROW_UP = "▴"

ERROR_NO_ID = "No ID supplied."
ERROR_INVALID_ID = "An invalid ID was provided."
ERROR_ACTION_UNAUTHORISED = ("You are not authorised to "
	"change this torrent")
ERROR_ACCESS_UNAUTHORISED = ("You are not authorised to "
	"view this page")

app = flask.Flask(__name__)
app.config.from_object(Config)

database = Database.Database()
utils = Utils.Utils(app)

torrent_list = {}
last_list = 0
list_lock = threading.Lock()
list_condition = threading.Condition()
def fill_torrent_list():
	global last_list
	global torrent_list
	while True:
		try:
			lines = utils.get_torrent_list()
		except:
			lines = []
		torrents = {}
		for i, line in enumerate(lines):
			if not line:
				continue
			line = line.rsplit(None, 14)
			owner = database.get_torrent_owner(line[-1])
			if not owner:
				database.add_torrent(line[-1], "root")
				owner = 1
			owner_username = database.username_from_id(
				owner)
			torrent = {"owner": owner, "name": line[0].lower(),
				"id": int(line[1]), "state": line[2],
				"percent": float(line[3][:-1]), "size":
				int(line[4]), "ratio": float(line[5]),
				"pretty_size": line[6], "info_hash": line[7],
				"uploader": owner_username, "title":
				line[0], "peers": line[8], "upload_speed":
				line[9], "download_speed": line[10],
				"uploaded": line[11], "downloaded": line[12],
				"have_pieces": line[13], "total_pieces":
				line[14]}
			if torrent["state"] in TORRENT_STATES:
				torrent["state"] = TORRENT_STATES[
					torrent["state"]]
			torrents[torrent["id"]] = torrent
		if lines:
			removed = set(torrent["info_hash"
				] for torrent in torrent_list.values())-set(
				torrent["info_hash"
				] for torrent in torrents.values())
			for info_hash in removed:
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
	return database.is_authenticated(
		flask.request.cookies.get("btpd-session"))
def is_admin():
	return database.is_admin(flask.request.cookies["btpd-session"])
def user_id():
	return database.id_from_session(flask.request.cookies[
		"btpd-session"])
def login_redirect():
	return flask.redirect(flask.url_for("login"))
def make_page(fragment, **kwargs):
	session = flask.request.cookies.get("btpd-session")
	user_username = database.username_from_session(session)
	user_admin = database.is_admin(session)
	return flask.render_template("index.html", fragment=fragment,
		user_username=user_username, user_admin=user_admin,
		**kwargs)
@app.route("/")
def index():
	if not is_authenticated():
		return login_redirect()
	session = flask.request.cookies["btpd-session"]
	admin = database.is_admin(session)
	user_id = database.id_from_session(session)
	orderby = flask.request.args.get("orderby", "0")
	descending = True
	headings = HEADINGS[:]
	if orderby and orderby.startswith("-"):
		descending = False
		orderby = orderby[1:]

	with list_lock:
		non_parsed_lines = copy.deepcopy(list(
			torrent_list.values()))
	if not orderby or not orderby.isdigit() or int(orderby
			) >= len(non_parsed_lines)-1:
		orderby = 0
	else:
		orderby = int(orderby)

	arrow = ARROW_DOWN if descending else ARROW_UP
	headings[orderby] = "%s %s" % (headings[orderby], arrow)
	parsed_lines = []
	for line in non_parsed_lines:
		if not admin and not line["owner"] == user_id:
			continue
		parsed_lines.append(line)
	orders = ["%s%d" % ("-" if n == orderby and descending else "",
		n) for n in range(len(HEADINGS))]
	if not orderby == 0:
		parsed_lines = sorted(parsed_lines,
			key=lambda l: l[HEADINGS[0].lower()],
			reverse=descending)
	parsed_lines = sorted(parsed_lines, key=lambda l: l[HEADINGS[
		orderby].lower()], reverse=descending)

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
		headings=headings, pages=pages, page=page,
		orderby=flask.request.args.get("orderby", 0))

@app.route("/action")
def action():
	if not is_authenticated():
		return login_redirect()
	if not "id" in flask.request.args:
		flask.abort(400, description=ERROR_NO_ID)
	id = flask.request.args["id"]
	if not id.isdigit() or not int(id) in torrent_list:
		flask.abort(400, description=ERROR_INVALID_ID)
	id = int(id)
	owner = torrent_list[id]["owner"]
	if not is_admin() and not user_id() == owner:
		flask.abort(401, description=
			ERROR_ACTION_UNAUTHORISED)

	state = torrent_list[id]["state"]
	if not state in TORRENT_ACTIONS:
		flask.abort(400, description="Unkown torrent state provided.")
	utils.do_torrent_action(id, TORRENT_ACTIONS[state])
	with list_condition:
		list_condition.notify()
	return flask.redirect(flask.request.referrer)

@app.route("/add", methods=["GET", "POST"])
def add():
	if not is_authenticated():
		return login_redirect()
	if flask.request.method == "POST":
		directory = flask.request.form["directory"].strip()
		if directory.startswith("/"):
			directory = directory[1:]
		if "../" in directory:
			return flask.abort(400, description="Invalid path provided")
		filename = "/tmp/btpd.%d." % os.getpid()
		if flask.request.form["torrenturl"].strip():
			filename = "%surl.%s.torrent" % (filename,
				hashlib.md5(flask.request.form[
				"torrenturl"].encode("utf8")
				).hexdigest())
			utils.download_torrent(
				flask.request.form["torrenturl"],
				filename)
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

		username = database.username_from_session(
			flask.request.cookies["btpd-session"])

		idle = "idle" in flask.request.form
		if not database.has_setting(username, "base_dir"):
			database.set_setting(username, "base_dir",
				app.config["BASE_DIR"])
		base_dir = database.get_setting(username, "base_dir")
		directory = os.path.join(base_dir, directory)

		utils.add_torrent(directory, filename, idle)
		os.remove(filename)
		with list_condition:
			list_condition.notify()

		database.add_torrent(info_hash, username)
		return flask.redirect(flask.url_for("index"))
	return make_page("add.html")

@app.route("/remove")
def remove():
	if not is_authenticated():
		return login_redirect()
	if not "id" in flask.request.args:
		flask.abort(400, description=ERROR_NO_ID)
	id = flask.request.args["id"]
	if not id.isdigit() or not int(id) in torrent_list:
		flask.abort(400, description=ERROR_INVALID_ID)
	id = int(id)
	owner = torrent_list[id]["owner"]
	if not is_admin() and not user_id() == owner:
		return flask.abort(401, description=
			ERROR_ACTION_UNAUTHORISED)
	if "seriously" in flask.request.args:
		with list_lock:
			info_hash = torrent_list[id]["info_hash"]
		if flask.request.args["seriously"] == "1":
			database.del_torrent(info_hash)
			utils.remove_torrent(id)
		with list_condition:
			list_condition.notify()
		return flask.redirect(flask.url_for("index"))
	else:
		with list_lock:
			title = torrent_list[id]["title"]
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
		database.del_session(flask.request.cookies[
			"btpd-session"])
	return login_redirect()

@app.route("/settings", methods=["GET", "POST"])
def settings():
	if not is_authenticated():
		return login_redirect()
	admin = is_admin()
	id = flask.request.args.get("id", flask.request.form.get(
		"id", ""))
	if not id.isdigit():
		id = None
	own_id = database.id_from_session(flask.request.cookies[
		"btpd-session"])
	if not id:
		id = own_id
	username = database.username_from_id(id)
	if (not admin and not id == own_id) or not username:
		flask.abort(401, description=
			ERROR_ACCESS_UNAUTHORISED)
	settings = database.get_all_settings(username)
	error = None
	saved = False
	if flask.request.method == "POST":
		for setting, value in flask.request.form.items():
			if error:
				break
			if not value:
				continue
			setting = setting.lower()
			if setting == "username" and not username == value:
				if database.id_from_username(value):
					error = "Username taken."
			elif setting == "password":
				if not flask.request.form["password_confirm"
						] == value:
					error = "Passwords do not match"
			elif setting == "base_dir" and not settings.get(
					"base_dir") == value:
				if not admin:
					error = ("You are not permitted to"
						" change your base directory")
		if not error:
			for setting, value in flask.request.form.items():
				if not value:
					continue
				if setting == "username" and not username == value:
					database.change_username(
						username, value)
				elif setting == "password":
					database.set_password(username, value)
				elif setting == "base_dir" and not settings.get(
						"base_dir") == value:
					database.set_setting(username,
						"base_dir", value)
				else:
					continue
				saved = True
		if saved:
			settings = database.get_all_settings(username)
	return make_page("settings.html", settings=settings,
		username=username, id=id, admin=admin, error=error,
		saved=saved)

@app.route("/users")
def users():
	if not is_admin():
		return login_redirect()
	users = database.list_users()
	for i, user in enumerate(users):
		user_dict = {}
		user_dict["id"] = user[0]
		user_dict["username"] = user[1]
		user_dict["admin"] = "✓" if user[2] == 1 else "✘"
		user_dict["torrent_count"] = database.torrent_count(
			user_dict["id"])
		users[i] = user_dict
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
		if database.has_username(username):
			return make_page("adduser.html",
				usernamefield=username,
				adduserfailed=True,
				warning="Username already in use")
		if not password == password_confirm:
			return make_page("adduser.html",
				usernamefield=username,
				adduserfailed=True,
				warning="Passwords do not match")
		database.add_user(username, password, admin)
		return flask.redirect(flask.url_for("users"))
	else:
		return make_page("adduser.html")

@app.route("/removeuser")
def remove_user():
	if not is_admin():
		return login_redirect()
	if not "id" in flask.request.args:
		flask.abort(400, description=ERROR_NO_ID)
	id = flask.request.args["id"]
	if "seriously" in flask.request.args:
		if flask.request.args["seriously"] == "1":
			database.del_user(id)
		return flask.redirect(flask.url_for(
			"users"))
	else:
		username = database.username_from_id(id)
		return make_page("userseriously.html",
			id=id, target_username=username,
			warning="Are you sure you want to remove"
			" this user?")

@app.route("/view")
def view():
	if not is_authenticated():
		return login_redirect()
	if not "id" in flask.request.args:
		flask.abort(400, description=ERROR_NO_ID)
	id = flask.request.args["id"]
	if not id.isdigit() or not int(id) in torrent_list:
		flask.abort(400, description=ERROR_INVALID_ID)
	id = int(id)
	owner = torrent_list[id]["owner"]
	if not is_admin() and not user_id() == owner:
		return flask.abort(401, description=
			ERROR_ACTION_UNAUTHORISED)
	torrent = torrent_list[id]
	return make_page("view.html", torrent=torrent)

@app.route("/log")
def log():
	lines = None
	if flask.request.args.get("lines") and flask.request.args[
			"lines"].isdigit():
		lines = int(flask.request.args["lines"])
	loglines = utils.get_log(lines)
	return make_page("log.html", lines=loglines)

if __name__ == "__main__":
	import ssl
	tls_context = None
	if app.config.get("TLS", False):
		assert "TLS_CERT" in app.config, ("No TLS certificate "
			"specified.")
		assert "TLS_KEY" in app.config, "No TLS key specified."
		tls_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
		tls_context.options = (ssl.OP_CIPHER_SERVER_PREFERENCE|
			ssl.OP_SINGLE_DH_USE|ssl.OP_SINGLE_ECDH_USE|
			ssl.OP_NO_COMPRESSION)
		tls_context.load_cert_chain(app.config["TLS_CERT"],
			app.config["TLS_KEY"])
		if "TLS_CIPHERS" in app.config:
			tls_context.set_ciphers(app.config[
				"TLS_CIPHERS"])
	bindhost = app.config.get("BINDHOST", "127.0.0.1")
	port = app.config.get("PORT", 5000)
	debug = app.config.get("DEBUG", False)
	list_thread.start()
	app.run(host=bindhost, port=port, debug=debug,
		ssl_context=tls_context)
