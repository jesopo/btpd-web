$(document).ready(function() {
	if ($("#takefocus").length) {
		$("#takefocus").focus();
	}
});

$(document).keyup(function(e) {
	var target = e.target.tagName.toLowerCase();
	if (target == "body") {
		var charHit = String.fromCharCode(e.which || e.keyCode
			).toLowerCase();
		if (charHit == 'n') {
			window.location.href = "/add";
		}
	}
});
