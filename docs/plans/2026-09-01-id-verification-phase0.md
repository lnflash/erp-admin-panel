# ID Verification — Phase 0 (ERPNext side)

> **Goal:** Give the upgrade-request review a real data model, a reason-coded decision, and an audit of record — before any automated checks exist.

**Scope:** `admin_panel` only. No flash changes, no desk page yet, no document checks yet. Everything here is what Phase 1's `flash-idv` service and the reviewer page will write into and read from.

---

## DocTypes

| DocType | Kind | What it holds |
|---|---|---|
| `ID Verification` | one per `Account Upgrade Request` (`upgrade_request` is unique; `IDV-#####`) | status, identity source, score, check report, evidence + checks child tables, Bridge snapshot, reviewer stamp + `decision_reason`, vendor fields |
| `Verification Evidence` | child table | one captured object (`id_front`, `selfie`, …): DO Spaces `file_key`, `sha256`, `content_type`, `captured_at`, `deleted_at` (retention job) |
| `Verification Check` | child table | one automated check: `check`, `result` pass/fail/unknown, `confidence`, extracted vs declared value |
| `Decision Reason` | registry (`field:code`) | `outcome` approve/reject/resubmit, reviewer `label`, `user_facing_message`, `active` |
| `Identity Document Type` | registry (`field:code`) | per-country accepted documents: MRZ, sides, base confidence, template keywords, `enabled`, `sample_verified`, `vendor_extraction` |
| `ID Verification Settings` | single | auto-approve policy (off by default), Bridge-KYC-satisfies-identity, retention years, `flash-idv` URL |
| `Compliance Audit Event` | append-only ledger | see below |

`Account Upgrade Request` gained `reviewed_by`, `reviewed_at`, `decision_reason` (after `support_note`). `get_upgrade_pulse` now counts the week's decisions by `reviewed_at`, falling back to `modified` only for rows decided before the stamp existed.

Statuses of `ID Verification`: `Checks pending` → `Ready for review` / `Checks unavailable` → `Approved` / `Rejected` / `Resubmit requested`. The controller refuses `Approved`/`Rejected` without `reviewed_by` + `reviewed_at`.

## Endpoints (`admin_panel.api.admin_api`, all `require_admin`)

- `approve_upgrade_request(request_id, reason_code=None)` — unchanged flash/ERP logic; then stamps the request (`reviewed_by/at`, `decision_reason`, default `APPROVE_VERIFIED`), mirrors the decision onto the request's `ID Verification` (get-or-create) and ledgers `upgrade_approved`. The reason code is validated **before** the flash call so a bad code can never leave flash upgraded and the request un-decided.
- `reject_upgrade_request(request_id, reason=None, reason_code=None)` — same, default `REJECT_OTHER`, ledgers `upgrade_rejected`.
- `request_resubmission(request_id, reason_code, note=None)` — request stays Pending; `ID Verification` → `Resubmit requested` with reason + note; `support_note` records the ask; ledgers `resubmission_requested`. Telling the user is flash-side (out of scope here).
- `get_id_document_url(file_key)` — unchanged contract (400 on errors, 502 on a null URL) plus an `evidence_viewed` ledger event on every successful mint. A view the ledger cannot record is not served.
- `get_id_verification(request_id)` → the `ID Verification` dict or `null`.
- `get_idv_settings()` → the Single's tunable fields.
- `admin_panel.api.compliance_audit.verify_audit_chain(limit=None)`, `get_audit_anchor()`.

## Compliance Audit Event — the hash chain

Rows are only ever written by `compliance_audit.record_event(event_type, reference_doctype, reference_name, payload)` with `ignore_permissions=True`; no role holds create/write/delete and the controller throws on any update or delete, Administrator included.

```
payload_json   = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
payload_sha256 = sha256(payload_json)
prev_hash      = hash of the newest row (created_at desc, creation desc), or "GENESIS"
hash           = sha256(prev_hash | event_type | actor | reference_doctype | reference_name | payload_sha256 | created_at)
```

`created_at` is hashed as `YYYY-MM-DDTHH:MM:SS.ffffff` whichever way it round-trips; `None` reference fields hash as empty strings so a NULL read back verifies. `verify_chain()` recomputes every row in created order and reports `{ok, checked, first_bad}`; `latest_anchor()` is `{hash, created_at, count}`. The head row is read `FOR UPDATE` so concurrent writers serialise instead of forking; a fork would surface as `first_bad`, and the unique index on `hash` rejects exact duplicates.

`post_daily_anchor()` (hooks `scheduler_events["daily"]`, **needs a scheduler worker**) posts the anchor to `site_config.ops_discord_webhook_url`; no-op when unset. Publishing the head outside the database is what makes an after-the-fact rewrite of the whole chain detectable.

Events written today: `upgrade_approved`, `upgrade_rejected`, `resubmission_requested`, `evidence_viewed`, `idv_settings_changed` (`{changed: {field: {from, to}}}`, skipped when nothing changed).

## Seeders (`admin_panel.admin_panel.setup`, run from `after_migrate`)

- `seed_decision_reasons()` — 14 codes. Insert-if-missing; re-asserts only `outcome` (the API validates a code's outcome against the action), leaves operator-tuned label/message/active alone.
- `seed_identity_document_types()` — 17 rows over Jamaica, Cayman Islands, Trinidad and Tobago, Barbados, Bahamas, El Salvador. Insert-only; a row whose Frappe `Country` is missing is skipped with a log line, never fatal.

## Phase 1 (next)

- **`flash-idv` service** — receives `{request, evidence file keys}`, runs document classification against `Identity Document Type`, OCR/MRZ, name/DOB match against the request, face match, expiry; writes `report_json` + `report_sha256`, the `checks` rows and `overall_score`; flips status to `Ready for review` / `Checks unavailable`. Auto-approve (gated by `ID Verification Settings`, sampled) lands here too.
- **ID Verification desk page** — queue by status, side-by-side evidence viewer (through `get_id_document_url`, so every view is ledgered), the check report, and approve / reject / resubmit buttons driving the endpoints above with a `Decision Reason` picker.
- Evidence ingestion from flash (`Verification Evidence` rows with `sha256` at capture time), Bridge KYC snapshotting for `identity_source = bridge_kyc`, and the retention job that sets `deleted_at`.
