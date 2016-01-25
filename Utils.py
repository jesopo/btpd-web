import subprocess

def get_torrent_list():
	lines = subprocess.check_output(["btcli", "list", "-f",
		"%n %# %t %p %S %r %s %h\\n"]).decode("utf8"
		).strip().split("\n")
	return lines

def do_torrent_action(id, action):
	subprocess.check_call(["btcli", action, str(id)])

def add_torrent(directory, torrent_file, idle=False):
	add_command = ["btcli", "add", "-d", directory,
		torrent_file]
	if idle:
		add_command.append("-N")
	subprocess.check_call(add_command)

def remove_torrent(id):
	subprocess.check_call(["btcli", "del", id])

def download_torrent(url, filename):
	subprocess.check_call(["wget", "-O", filename, url])
