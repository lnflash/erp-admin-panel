"""Behavioural tests for the Alert Users desk page.

The page decides, per click, whether a message goes to one named customer or to
every Flash user — a decision no source-grep can meaningfully guard. These run
the real alert_users.js under Node against a jQuery / frappe shim (see
js/alert_users_harness.js) and assert on what the page actually did: which
endpoint it called, with which arguments, what it cleared afterwards, and
whether a second click could get through while the first send was in flight.

Node is not a build dependency of the app, so the module skips when it is
absent rather than failing the suite.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "js" / "alert_users_harness.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to drive the page harness")


@pytest.fixture(scope="module")
def page():
	"""Run every harness scenario once and hand back the observations."""
	completed = subprocess.run(
		[NODE, str(HARNESS)],
		capture_output=True,
		text=True,
		check=False,
	)
	assert completed.returncode == 0, f"harness failed:\n{completed.stderr}"
	return json.loads(completed.stdout)


# --- audience routing ---


def test_specific_user_calls_send_user_alert_with_the_typed_recipient(page):
	# The failure this guards: a flipped audience check turns a personal
	# support message into a broadcast to every Flash user.
	result = page["direct_send_routes_to_send_user_alert"]

	assert result["method"] == "admin_panel.api.admin_api.send_user_alert"
	assert result["args"] == {
		"username": "jaceth2009",
		"title": "Update Flash",
		"message": "Please update your app.",
	}
	# The @ prefix is stripped client-side; no topic is sent on this path.
	assert "alert_type" not in result["args"]
	assert result["broadcasts"] == 0


def test_all_users_calls_send_alert_with_the_chosen_topic(page):
	result = page["broadcast_send_routes_to_send_alert"]

	assert result["method"] == "admin_panel.api.admin_api.send_alert"
	assert result["args"] == {
		"title": "Update Flash",
		"message": "Please update your app.",
		"alert_type": "EMERGENCY",
	}
	assert "username" not in result["args"]
	assert result["directs"] == 0


def test_switching_back_to_broadcast_drops_the_typed_recipient(page):
	result = page["a_stale_username_never_rides_along_with_a_broadcast"]

	assert result["method"] == "admin_panel.api.admin_api.send_alert"
	assert "username" not in result["args"]


# --- post-send reset ---


def test_a_successful_send_clears_the_recipient_with_the_message(page):
	# Clearing the message but keeping @alice in the box is how the next
	# alert, typed for @bob, reaches the wrong customer.
	result = page["a_successful_send_clears_the_recipient"]

	assert result["username"] == ""
	assert result["title"] == ""
	assert result["message"] == ""
	# The preview follows the cleared field back to its placeholder.
	assert result["previewAudience"] == "to @username"


def test_a_failed_send_leaves_the_form_alone(page):
	result = page["a_failed_send_keeps_the_form_intact"]

	assert result["username"] == "jaceth2009"
	assert result["title"] == "Update Flash"
	assert result["message"] == "Please update your app."
	assert result["msgprints"][0]["message"] == "Failed to send alert: Not a Flash username"


def test_a_clean_send_says_nothing_about_the_audit_row(page):
	# Negative control for the warning below: crying wolf on every send teaches
	# the operator to dismiss the one dialog that matters.
	assert page["a_successful_send_clears_the_recipient"]["msgprints"] == []


def test_a_delivered_but_unaudited_send_tells_the_operator_not_to_resend(page):
	# The server returns success=True plus a warning when the push was delivered
	# but the audit row failed to write. Dropping the warning leaves the operator
	# believing the send is logged; treating it as a failure would keep the form
	# intact and invite a second push to the same customer.
	result = page["a_delivered_but_unaudited_send_warns_the_operator"]

	assert result["msgprints"][0]["title"] == "Sent — audit row failed"
	assert "do not resend" in result["msgprints"][0]["message"]
	assert result["msgprints"][0]["indicator"] == "orange"
	# Still a success: the green toast fires and the form clears, so nothing
	# nudges the operator into sending again.
	assert result["alerts"][0]["indicator"] == "green"
	assert result["username"] == ""
	assert result["title"] == ""
	assert result["message"] == ""


def test_a_delivered_but_unaudited_broadcast_tells_the_operator_not_to_resend(page):
	# send_alert carries the same warning contract as its single-user sibling, and
	# the page's callback is shared between them. A broadcast has already reached
	# every Flash user by the time the audit row fails, so a dropped warning here
	# is the widest version of this defect.
	result = page["a_delivered_but_unaudited_broadcast_warns_the_operator"]

	assert result["msgprints"][0]["title"] == "Sent — audit row failed"
	assert "do not resend" in result["msgprints"][0]["message"]
	assert result["msgprints"][0]["indicator"] == "orange"
	assert result["alerts"][0]["indicator"] == "green"
	assert result["title"] == ""
	assert result["message"] == ""


# --- in-flight guard ---


def test_topics_landing_mid_send_cannot_re_enable_the_button(page):
	# A direct alert is sendable before the topic list loads, so a slow
	# get_alert_types response can return while send_user_alert is still in
	# flight. Re-enabling there would let a reflexive second click push the
	# same notification to the customer twice and write two DIRECT audit rows.
	result = page["topics_arriving_mid_send_cannot_re_enable_the_button"]

	assert result["whileSending"]["disabled"] is True
	assert "Sending..." in result["whileSending"]["label"]
	assert result["afterTopics"]["disabled"] is True
	assert "Sending..." in result["afterTopics"]["label"]
	assert result["sendCalls"] == 1
	assert result["confirms"] == 1


def test_the_button_returns_once_the_send_settles(page):
	# Negative control: the guard must release, or the page is stuck after one
	# send and "always disabled" would pass the test above.
	result = page["the_button_comes_back_once_the_send_settles"]

	assert result["afterSettle"]["disabled"] is False
	assert "Send Alert to User" in result["afterSettle"]["label"]
	assert result["confirms"] == 2


def test_a_direct_send_does_not_wait_for_the_topic_list(page):
	result = page["a_direct_send_does_not_wait_for_topics"]

	assert result["broadcastBeforeTopics"]["disabled"] is True
	assert result["directBeforeTopics"]["disabled"] is False
	assert result["broadcastAfterTopics"]["disabled"] is False


# --- guards and rendering ---


def test_a_blank_recipient_never_reaches_the_confirm_dialog(page):
	result = page["a_missing_recipient_blocks_the_send"]

	assert result["confirms"] == 0
	assert result["sendCalls"] == 0
	assert result["msgprintTitles"] == ["Missing Username"]
	assert result["usernameFocused"] is True


def test_the_confirm_dialog_names_the_target_and_escapes_operator_input(page):
	result = page["the_confirm_dialog_names_and_escapes_the_target"]

	assert "<strong>@ali&lt;b&gt;ce</strong>" in result["confirmMessage"]
	assert "&lt;script&gt;x&lt;/script&gt;" in result["confirmMessage"]
	assert "<script>" not in result["confirmMessage"]


def test_the_broadcast_confirm_dialog_escapes_the_topic(page):
	# Topics are whatever the flash admin query returns, and the broadcast dialog
	# interpolates one twice. It also has to survive the round trip through the
	# rendered <option> value, or the confirm dialog names a different topic than
	# the one the broadcast is sent under.
	result = page["the_broadcast_confirm_dialog_escapes_the_topic"]

	assert "&lt;img src=x onerror=alert(1)&gt;&quot;EMERGENCY" in result["confirmMessage"]
	assert "<img" not in result["confirmMessage"]
	assert result["confirmMessage"].count("&lt;img") == 2
	# The option value carries the same escaping, so val() cannot come back
	# truncated at the double quote.
	assert "<img" not in result["topicOptionsHtml"]
	assert '<option value="&lt;img src=x onerror=alert(1)&gt;&quot;EMERGENCY">' in result["topicOptionsHtml"]


def test_history_distinguishes_direct_rows_from_broadcasts(page):
	html = page["history_labels_direct_and_broadcast_rows"]["html"]

	assert "to @bo&lt;b&gt;b" in html
	assert "to all users" in html
	assert "<b>" not in html


def test_history_refuses_to_call_a_targetless_row_a_broadcast_mid_migrate(page):
	# While the migrate that adds target_username is still running the endpoint
	# drops the column, so a DIRECT row arrives with no target. Labelling it
	# "to all users" tells the operator a private support message went to every
	# Flash user. The page has to say it does not know.
	html = page["history_admits_it_cannot_name_the_recipient_mid_migrate"]["html"]

	assert html.count("recipient unavailable") == 2
	assert "to all users" not in html


def test_history_still_labels_real_broadcasts_when_the_column_is_present(page):
	# Negative control: "recipient unavailable" everywhere would pass the test
	# above and destroy the panel's normal reading.
	html = page["history_labels_broadcasts_normally_once_the_column_is_back"]["html"]

	assert html.count("to all users") == 2
	assert "recipient unavailable" not in html


def test_the_preview_follows_the_audience(page):
	result = page["the_preview_tracks_the_chosen_audience"]

	assert result["broadcast"] == {"audience": "to all users", "tag": "MARKETING"}
	assert result["direct"] == {"audience": "to @jaceth2009", "tag": "DIRECT"}
