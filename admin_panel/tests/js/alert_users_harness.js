/**
 * Behavioural harness for the Alert Users desk page.
 *
 * The page ships as a plain frappe desk script, so there is no bundler or
 * browser in the test path. This loads the real alert_users.js against a
 * hand-rolled shim covering exactly the jQuery / frappe surface the page
 * touches (find-by-selector, val/text/html/prop/attr, show/hide/fadeIn, event
 * handlers, frappe.call / confirm / msgprint / show_alert / utils / datetime),
 * drives each scenario, and prints the observations as JSON for
 * test_alert_users_page_behavior.py to assert on.
 *
 * frappe.call never invokes its callbacks here — scenarios resolve them by
 * hand, which is what makes the in-flight ordering testable.
 */

const fs = require("fs");
const path = require("path");

const PAGE_JS = path.join(
	__dirname,
	"..",
	"..",
	"admin_panel",
	"page",
	"alert_users",
	"alert_users.js"
);

const HTML_ESCAPES = {
	"&": "&amp;",
	"<": "&lt;",
	">": "&gt;",
	'"': "&quot;",
	"'": "&#39;",
};

function escapeHtml(text) {
	if (text === undefined || text === null) return "";
	return String(text).replace(/[&<>"']/g, function (char) {
		return HTML_ESCAPES[char];
	});
}

function makeElement(selector) {
	const el = {
		selector: selector,
		value: "",
		textContent: "",
		htmlContent: "",
		visible: true,
		focused: false,
		props: {},
		attrs: {},
		handlers: {},
	};

	el.val = function (next) {
		if (next === undefined) return el.value;
		el.value = String(next);
		return el;
	};
	el.text = function (next) {
		if (next === undefined) return el.textContent;
		el.textContent = String(next);
		return el;
	};
	el.html = function (next) {
		if (next === undefined) return el.htmlContent;
		el.htmlContent = String(next);
		return el;
	};
	el.append = function (chunk) {
		el.htmlContent += String(chunk);
		return el;
	};
	el.empty = function () {
		el.htmlContent = "";
		return el;
	};
	el.prop = function (name, next) {
		if (next === undefined) return el.props[name];
		el.props[name] = next;
		return el;
	};
	el.attr = function (name, next) {
		if (next === undefined) return el.attrs[name];
		el.attrs[name] = next;
		return el;
	};
	el.show = function () {
		el.visible = true;
		return el;
	};
	el.hide = function () {
		el.visible = false;
		return el;
	};
	el.fadeIn = function () {
		el.visible = true;
		return el;
	};
	el.focus = function () {
		el.focused = true;
		return el;
	};
	el.on = function (event, handler) {
		if (!el.handlers[event]) el.handlers[event] = [];
		el.handlers[event].push(handler);
		return el;
	};
	el.fire = function (event) {
		(el.handlers[event] || []).forEach(function (handler) {
			handler.call(el);
		});
		return el;
	};

	return el;
}

// jQuery's `$(this)` inside a handler — `this` is already our element shim.
function jq(target) {
	return target;
}

function noop() {}

function load() {
	const root = makeElement(":root");
	const elements = {};
	root.find = function (selector) {
		if (!elements[selector]) elements[selector] = makeElement(selector);
		return elements[selector];
	};

	// Mirror the rendered markup's defaults: the audience select opens on
	// "all", the topic select is empty until get_alert_types answers.
	root.find("#alert-audience").val("all");
	root.find("#alert-tag").val("");

	const calls = [];
	const confirms = [];
	const msgprints = [];
	const alerts = [];

	const frappe = {
		pages: { "alert-users": {} },
		ui: {
			make_app_page: function () {
				return { main: root };
			},
		},
		call: function (options) {
			calls.push(options);
		},
		confirm: function (message, onYes) {
			confirms.push({ message: message, run: onYes });
		},
		msgprint: function (options) {
			msgprints.push(options);
		},
		show_alert: function (options) {
			alerts.push(options);
		},
		utils: { escape_html: escapeHtml },
		datetime: { str_to_user: String },
	};

	const factory = new Function("frappe", "$", fs.readFileSync(PAGE_JS, "utf8"));
	factory(frappe, jq);
	frappe.pages["alert-users"].on_page_load({});

	const ctx = {
		root: root,
		frappe: frappe,
		calls: calls,
		confirms: confirms,
		msgprints: msgprints,
		alerts: alerts,
	};

	ctx.el = function (selector) {
		return root.find(selector);
	};
	ctx.callsTo = function (method) {
		return calls.filter(function (call) {
			return call.method === "admin_panel.api.admin_api." + method;
		});
	};
	// Never undefined: a routing regression should surface as a readable
	// assertion on the Python side, not a TypeError inside the harness.
	ctx.lastCallTo = function (method) {
		const matches = ctx.callsTo(method);
		return (
			matches[matches.length - 1] || {
				method: null,
				args: null,
				callback: noop,
				always: noop,
			}
		);
	};
	ctx.sendButton = function () {
		return root.find("#send-alert-btn");
	};
	ctx.compose = function (fields) {
		if (fields.audience !== undefined) {
			ctx.el("#alert-audience").val(fields.audience).fire("change");
		}
		if (fields.username !== undefined) {
			ctx.el("#alert-username").val(fields.username).fire("input");
		}
		if (fields.alertType !== undefined) {
			ctx.el("#alert-tag").val(fields.alertType).fire("change");
		}
		if (fields.title !== undefined) {
			ctx.el("#alert-title").val(fields.title).fire("input");
		}
		if (fields.message !== undefined) {
			ctx.el("#alert-description").val(fields.message).fire("input");
		}
		return ctx;
	};
	ctx.clickSend = function () {
		ctx.sendButton().fire("click");
		return ctx;
	};
	ctx.acceptConfirm = function () {
		const dialog = confirms[confirms.length - 1] || { message: null, run: noop };
		dialog.run();
		return dialog;
	};
	ctx.deliverTopics = function (topics) {
		ctx.lastCallTo("get_alert_types").callback({ message: { topics: topics } });
		return ctx;
	};
	// `extra` carries the rest of the get_user_alerts payload —
	// target_username_available, which the endpoint sets false while the migrate
	// that adds the column is still running. Omit it to exercise the pre-flag
	// server contract.
	ctx.deliverHistory = function (logs, extra) {
		const message = { logs: logs };
		Object.keys(extra || {}).forEach(function (key) {
			message[key] = extra[key];
		});
		ctx.lastCallTo("get_user_alerts").callback({ message: message });
		return ctx;
	};
	ctx.buttonState = function () {
		return {
			disabled: ctx.sendButton().prop("disabled"),
			label: ctx.sendButton().html(),
		};
	};

	return ctx;
}

const USERNAME = "jaceth2009";
const TITLE = "Update Flash";
const MESSAGE = "Please update your app.";

const scenarios = {};

// --- audience routing -------------------------------------------------------

scenarios.direct_send_routes_to_send_user_alert = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: "@" + USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	const dialog = ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_user_alert");
	return {
		confirmMessage: dialog.message,
		method: call.method,
		args: call.args,
		broadcasts: ctx.callsTo("send_alert").length,
	};
};

scenarios.broadcast_send_routes_to_send_alert = function () {
	const ctx = load();
	ctx.deliverTopics(["EMERGENCY", "MARKETING"]);
	ctx.compose({ audience: "all", alertType: "EMERGENCY", title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_alert");
	return {
		method: call.method,
		args: call.args,
		directs: ctx.callsTo("send_user_alert").length,
	};
};

scenarios.a_stale_username_never_rides_along_with_a_broadcast = function () {
	// Typing a recipient, then switching back to "All users", must not smuggle
	// the username into the broadcast call.
	const ctx = load();
	ctx.deliverTopics(["MARKETING"]);
	ctx.compose({ audience: "user", username: USERNAME });
	ctx.compose({ audience: "all", alertType: "MARKETING", title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_alert");
	return { method: call.method, args: call.args };
};

// --- post-send reset --------------------------------------------------------

scenarios.a_successful_send_clears_the_recipient = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_user_alert");
	call.callback({ message: { success: true } });
	call.always();
	return {
		username: ctx.el("#alert-username").val(),
		title: ctx.el("#alert-title").val(),
		message: ctx.el("#alert-description").val(),
		previewAudience: ctx.el("#preview-audience").text(),
		// Negative control for the audit-warning scenario below: a clean send
		// must raise no dialog at all.
		msgprints: ctx.msgprints,
	};
};

scenarios.a_delivered_but_unaudited_send_warns_the_operator = function () {
	// The server reports a delivered push whose audit row failed to write as a
	// success carrying a warning. Ignoring the warning leaves the operator
	// believing the send was fully logged; treating it as a failure would push
	// them into re-sending a notification the customer already has.
	const ctx = load();
	ctx.compose({ audience: "user", username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_user_alert");
	call.callback({
		message: {
			success: true,
			message: "Notification sent to @" + USERNAME + ": " + TITLE,
			warning: "Sent, but the audit row failed to write — do not resend.",
		},
	});
	call.always();
	return {
		msgprints: ctx.msgprints,
		alerts: ctx.alerts,
		username: ctx.el("#alert-username").val(),
		title: ctx.el("#alert-title").val(),
		message: ctx.el("#alert-description").val(),
	};
};

scenarios.a_delivered_but_unaudited_broadcast_warns_the_operator = function () {
	// send_alert reports a delivered-but-unaudited broadcast exactly the way its
	// single-user sibling does, and the callback above is shared between the two
	// endpoints. Rendering the warning only on the DIRECT branch would leave a
	// push that already reached every Flash user looking fully logged when no row
	// exists for it.
	const ctx = load();
	ctx.deliverTopics(["MARKETING"]);
	ctx.compose({ audience: "all", alertType: "MARKETING", title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_alert");
	call.callback({
		message: {
			success: true,
			message: "Notification sent successfully: " + TITLE,
			warning: "Sent, but the audit row failed to write — do not resend.",
		},
	});
	call.always();
	return {
		msgprints: ctx.msgprints,
		alerts: ctx.alerts,
		title: ctx.el("#alert-title").val(),
		message: ctx.el("#alert-description").val(),
	};
};

scenarios.a_failed_send_keeps_the_form_intact = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_user_alert");
	call.callback({ message: { success: false, error: "Not a Flash username" } });
	call.always();
	return {
		username: ctx.el("#alert-username").val(),
		title: ctx.el("#alert-title").val(),
		message: ctx.el("#alert-description").val(),
		msgprints: ctx.msgprints,
	};
};

// --- in-flight guard --------------------------------------------------------

scenarios.topics_arriving_mid_send_cannot_re_enable_the_button = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const whileSending = ctx.buttonState();

	// The slow get_alert_types response lands mid-send and calls
	// setSendButtonIdle(). It must not resurrect the button.
	ctx.deliverTopics(["EMERGENCY"]);
	const afterTopics = ctx.buttonState();

	// A reflexive second click while still in flight.
	ctx.clickSend();

	return {
		whileSending: whileSending,
		afterTopics: afterTopics,
		sendCalls: ctx.callsTo("send_user_alert").length,
		confirms: ctx.confirms.length,
	};
};

scenarios.the_button_comes_back_once_the_send_settles = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();
	ctx.acceptConfirm();
	const call = ctx.lastCallTo("send_user_alert");
	call.callback({ message: { success: true } });
	call.always();
	const afterSettle = ctx.buttonState();

	ctx.compose({ username: USERNAME, title: TITLE, message: MESSAGE });
	ctx.clickSend();

	return { afterSettle: afterSettle, confirms: ctx.confirms.length };
};

scenarios.a_direct_send_does_not_wait_for_topics = function () {
	const ctx = load();
	const broadcastBeforeTopics = ctx.buttonState();
	ctx.compose({ audience: "user" });
	const directBeforeTopics = ctx.buttonState();
	ctx.compose({ audience: "all" });
	ctx.deliverTopics(["MARKETING"]);
	const broadcastAfterTopics = ctx.buttonState();
	return {
		broadcastBeforeTopics: broadcastBeforeTopics,
		directBeforeTopics: directBeforeTopics,
		broadcastAfterTopics: broadcastAfterTopics,
	};
};

// --- guards and rendering ---------------------------------------------------

scenarios.a_missing_recipient_blocks_the_send = function () {
	const ctx = load();
	ctx.compose({ audience: "user", username: "   ", title: TITLE, message: MESSAGE });
	ctx.clickSend();
	return {
		confirms: ctx.confirms.length,
		sendCalls: ctx.callsTo("send_user_alert").length,
		msgprintTitles: ctx.msgprints.map(function (m) {
			return m.title;
		}),
		usernameFocused: ctx.el("#alert-username").focused,
	};
};

scenarios.the_confirm_dialog_names_and_escapes_the_target = function () {
	const ctx = load();
	ctx.compose({
		audience: "user",
		username: "ali<b>ce",
		title: "<script>x</script>",
		message: MESSAGE,
	});
	ctx.clickSend();
	return { confirmMessage: (ctx.confirms[0] || {}).message };
};

scenarios.the_broadcast_confirm_dialog_escapes_the_topic = function () {
	// Topics come back from the flash admin query, not from a fixed list, so the
	// dialog that asks "send this <topic> alert to all users?" renders a value
	// this page did not author. It appears twice in that message.
	const ctx = load();
	const hostileTopic = '<img src=x onerror=alert(1)>"EMERGENCY';
	ctx.deliverTopics([hostileTopic]);
	ctx.compose({
		audience: "all",
		alertType: hostileTopic,
		title: TITLE,
		message: MESSAGE,
	});
	ctx.clickSend();
	return {
		confirmMessage: (ctx.confirms[0] || {}).message,
		topicOptionsHtml: ctx.el("#alert-tag").html(),
	};
};

scenarios.history_labels_direct_and_broadcast_rows = function () {
	const ctx = load();
	ctx.deliverHistory([
		{
			title: "Update Flash",
			message: "Please update.",
			tag: "DIRECT",
			target_username: "bo<b>b",
			sent_by: "ops@getflash.io",
			sent_on: "2026-08-19 12:00:00",
		},
		{
			title: "Scheduled maintenance",
			message: "Back at 9.",
			tag: "EMERGENCY",
			sent_by: "ops@getflash.io",
			sent_on: "2026-08-18 12:00:00",
		},
	]);
	return { html: ctx.el("#alert-history-list").html() };
};

const PRE_MIGRATE_ROWS = [
	// What the endpoint returns once it has dropped target_username from the
	// select: the DIRECT row is indistinguishable from the broadcast below it.
	{
		title: "Update Flash",
		message: "Please update.",
		tag: "DIRECT",
		sent_by: "ops@getflash.io",
		sent_on: "2026-08-19 12:00:00",
	},
	{
		title: "Scheduled maintenance",
		message: "Back at 9.",
		tag: "EMERGENCY",
		sent_by: "ops@getflash.io",
		sent_on: "2026-08-18 12:00:00",
	},
];

scenarios.history_admits_it_cannot_name_the_recipient_mid_migrate = function () {
	const ctx = load();
	ctx.deliverHistory(PRE_MIGRATE_ROWS, { target_username_available: false });
	return { html: ctx.el("#alert-history-list").html() };
};

scenarios.history_labels_broadcasts_normally_once_the_column_is_back = function () {
	// Negative control: the same targetless rows with the column present are
	// genuine broadcasts and must still read "to all users".
	const ctx = load();
	ctx.deliverHistory(PRE_MIGRATE_ROWS, { target_username_available: true });
	return { html: ctx.el("#alert-history-list").html() };
};

scenarios.the_preview_tracks_the_chosen_audience = function () {
	const ctx = load();
	ctx.deliverTopics(["MARKETING"]);
	ctx.compose({ audience: "all", alertType: "MARKETING", title: TITLE, message: MESSAGE });
	const broadcast = {
		audience: ctx.el("#preview-audience").text(),
		tag: ctx.el("#preview-tag").text(),
	};
	ctx.compose({ audience: "user", username: USERNAME });
	const direct = {
		audience: ctx.el("#preview-audience").text(),
		tag: ctx.el("#preview-tag").text(),
	};
	return { broadcast: broadcast, direct: direct };
};

const results = {};
Object.keys(scenarios).forEach(function (name) {
	results[name] = scenarios[name]();
});
process.stdout.write(JSON.stringify(results));
