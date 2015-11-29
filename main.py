#!/usr/bin/env python3

import subprocess, time
import flask
import Config

TORRENT_STATES = {"S": "seed", "I": "idle", "L": "leech", "+": "starting"}
TORRENT_ACTIONS = {"seed": "stop", "idle": "start", "leech": "start"}

app = flask.Flask(__name__)
app.config.from_object(Config)

@app.route("/")
def index():
	orderby = flask.request.args.get("orderby")
	reverse = False
	if orderby and orderby.startswith("-"):
		reverse = True
		orderby = orderby[1:]
	lines = subprocess.check_output(["btcli", "list", "-f", "%n %# %t %p %s %r\\n"]
		).decode("utf8").strip().split("\n")
	if not orderby or not orderby.isdigit() or int(orderby) > len(lines)-1:
		orderby = 0
	else:
		orderby = int(orderby)
	parsed_lines = []
	failed = False
	if lines[0].startswith("cannot open connection"):
		failed = True
	else:
		for line in lines[1:]:
			line = line.rsplit(None, 5)
			if line[2] in TORRENT_STATES:
				line[2] = TORRENT_STATES[line[2]]
			parsed_lines.append(line)
	orders = ["%s%d" % ("-" if n == orderby and not reverse else "", n) for n in range(6)]
	parsed_lines = sorted(parsed_lines, key=lambda l: l[orderby], reverse=reverse)
	return flask.render_template("index.html", failed=failed,
		lines=parsed_lines, orders=orders)
@app.route("/action")
def torrent_action():
	print(flask.request.referrer)
	referrer_params = flask.request.referrer.split("?", 1)
	if len(referrer_params) > 1:
		referrer_params = "?%s" % referrer_params[1]
	else:
		referrer_params = ""
	state = flask.request.args["state"]
	id = flask.request.args["id"]
	if not id.isdigit() or not state in TORRENT_ACTIONS:
		return flask.abort(400)
	print(TORRENT_ACTIONS[state])
	out = subprocess.check_output(["btcli", TORRENT_ACTIONS[state], id],
		stderr=subprocess.STDOUT)
	if not flask.request.is_xhr:
		return flask.redirect("%s%s" % (flask.url_for("index"), referrer_params))
	return "0" if out else "1"
if __name__ == "__main__":
	app.run(host="0.0.0.0", debug=True)

