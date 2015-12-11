#!/usr/bin/env python3

import subprocess, time
import flask
import Config

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "start"}

HEADINGS= ["ID", "Name", "Status", "Percent", "Size", "Ratio"]
ARROW_DOWN = "▾"
ARROW_UP = "▴"

app = flask.Flask(__name__)
app.config.from_object(Config)

def get_referrer_params():
	if flask.request.referrer:
		referrer_params = flask.request.referrer.split("?", 1)
		if len(referrer_params) > 1:
			return "?%s" % referrer_params[1]
	return ""

@app.route("/")
def index():
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
	state = flask.request.args["state"]
	id = flask.request.args["id"]
	if not id.isdigit() or not state in TORRENT_ACTIONS:
		return flask.abort(400)
	out = subprocess.check_output(["btcli", TORRENT_ACTIONS[state], id],
		stderr=subprocess.STDOUT)
	if not flask.request.is_xhr:
		return flask.redirect("%s%s" % (flask.url_for("index"), referrer_params))
	return "0" if out else "1"

@app.route("/add")
def add():
	failed = False
	if flask.request.method == "POST":
		directory = flask.request.form["directory"]
		file = flask.request.files["file"]
		file.save("/tmp/torrent")
		try:
			subprocess.check_call(["btcli", "add", "-d",
				os.path.join(app.config["BASEDIR"], directory),
				"/tmp/torrent"])
			return flask.redirect(flask.url_for("index"))
		except:
			failed = True
	return flask.render_template("index.html",
		fragment="add.html", failed=failed)
@app.route("/remove")
def remove():
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

if __name__ == "__main__":
	app.run(host="0.0.0.0", debug=True)

