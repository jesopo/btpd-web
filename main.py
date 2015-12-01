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

@app.route("/")
def index():
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
	referrer_params = flask.request.referrer.split("?", 1)
	if len(referrer_params) > 1:
		referrer_params = "?%s" % referrer_params[1]
	else:
		referrer_params = ""
	state = flask.request.args["state"]
	id = flask.request.args["id"]
	if not id.isdigit() or not state in TORRENT_ACTIONS:
		return flask.abort(400)
	out = subprocess.check_output(["btcli", TORRENT_ACTIONS[state], id],
		stderr=subprocess.STDOUT)
	if not flask.request.is_xhr:
		return flask.redirect("%s%s" % (flask.url_for("index"), referrer_params))
	return "0" if out else "1"

if __name__ == "__main__":
	app.run(host="0.0.0.0", debug=True)

