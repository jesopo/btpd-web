$(document).ready(function() {
	if ($("#takefocus").length) {
		$("#takefocus").focus();
	}
});

$(document).keydown(function(e) {
	var target = e.target.tagName.toLowerCase();
	if (target != "input") {
		var charHit = String.fromCharCode(e.which || e.keyCode
			).toLowerCase();
		if ($.trim(charHit) != "") {
			if (charHit == 'n') {
				window.location.href = "/add";
			} else if (charHit == 'h') {
				window.location.href = "/";
			} else if (!isNaN(charHit) && $(".torrentheadings").length) {
				var headings = $(".torrents").find(".torrentheading")
				var number = parseInt(charHit)-1;
				if (number < headings.length) {
					var heading = $(headings.get(number));
					window.location.href  = heading.attr("href");
				}
			}
		}
	}
});
