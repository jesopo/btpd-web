import os, subprocess

class Utils(object):
	def __init__(self, app):
		self.app = app
		self.btpd_dir = app.config.get("BTPD_DIR"
			) or os.path.join(os.path.expanduser("~"),
			".btpd")
	def get_torrent_list(self):
		lines = subprocess.check_output(["btcli", "-d",
			self.btpd_dir, "list", "-f",
			"%n %# %t %p %S %r %s %h %P %^ %v %u %g "
			"%H %T\\n"]
			).decode("utf8").strip().split("\n")
		return lines
	def do_torrent_action(self, id, action):
		subprocess.check_call(["btcli", "-d", self.btpd_dir,
			 action, str(id)])
	def add_torrent(self, directory, torrent_file, idle=False):
		add_command = ["btcli", "-d", self.btpd_dir, "add",
			"-d", directory, torrent_file]
		if idle:
			add_command.append("-N")
		subprocess.check_call(add_command)
	def remove_torrent(self, id):
		subprocess.check_call(["btcli", "-d", self.btpd_dir,
			"del", str(id)])
	def download_torrent(self, url, filename):
		subprocess.check_call(["wget", "-O", filename, url])
	def get_log(self, lines):
		lines = lines or self.app.config.get("LOG_LINES", 30)
		with open(os.path.join(self.btpd_dir, "log"), "rb"
				) as log:
			return log.read().decode("utf8", "ignore"
				).strip().split("\n")[-lines:][::-1]
