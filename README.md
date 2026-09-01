### Admin Panel

Extension to ERPnext for Flash admin users to manage the accounts & services.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app admin_panel
```

### Architecture

#### DocTypes

App-owned DocTypes (`User Alerts`, `Account Upgrade Request`, the ID-verification set below, …) are defined as module-level JSON files, not fixtures:

```
admin_panel/admin_panel/doctype/
├── user_alerts/
│   ├── user_alerts.json   ← schema definition
│   └── user_alerts.py     ← Python controller
└── account_upgrade_request/
    ├── account_upgrade_request.json
    └── account_upgrade_request.py
```

`bench migrate` reads these JSON files via `sync_all()` and applies any schema changes (e.g. `ALTER TABLE`) automatically. **Do not add these DocTypes to `fixtures`** — fixtures are for configuration records on *existing* doctypes (Custom Fields, Roles, etc.), not for app-owned types.

**To modify a DocType:**
1. Edit the JSON file directly — add, remove, or update fields
2. Update the `modified` timestamp to the current UTC datetime
3. Add the field name to `field_order` if adding a new field
4. Build and deploy a new Docker image
5. Run `bench migrate` — the schema change is applied automatically

**To add a new DocType:**
1. Create `admin_panel/admin_panel/doctype/{doctype_name}/` with `{doctype_name}.json`, `{doctype_name}.py`, and `__init__.py`
2. Set `"custom": 0` and `"module": "Admin Panel"` in the JSON
3. Follow the same deploy + migrate flow above

#### ID verification (Phase 0)

The upgrade-request review is backed by `ID Verification` (one per request, with `Verification Evidence` / `Verification Check` child tables), the `Decision Reason` and `Identity Document Type` registries (seeded from `after_migrate`), the `ID Verification Settings` single, and `Compliance Audit Event` — an append-only, hash-chained ledger written only by `admin_panel.api.compliance_audit.record_event`. Decision endpoints (`approve_upgrade_request`, `reject_upgrade_request`, `request_resubmission`, `get_id_verification`, `get_idv_settings`) live in `admin_panel.api.admin_api`; `verify_audit_chain` / `get_audit_anchor` in `admin_panel.api.compliance_audit`. The daily `post_daily_anchor` scheduler job needs a scheduler worker. Design and Phase 1 scope: [docs/plans/2026-09-01-id-verification-phase0.md](docs/plans/2026-09-01-id-verification-phase0.md).

#### Pages

Pages (`alert-users`, `account-management`) are defined in the module directory:

```
admin_panel/admin_panel/page/
├── alert_users/
│   ├── alert_users.json   ← page metadata
│   └── alert_users.js     ← page UI
└── account_management/
    ├── account_management.json
    └── account_management.js
```

Page metadata (name, title, module) is synced to the database via the `after_migrate` hook in `admin_panel/setup.py`, which runs automatically as part of `bench migrate`. The hook uses `flags.ignore_validate` to bypass Frappe's developer-mode restriction on Page writes. **Do not add Pages to `fixtures`** — doing so requires `developer_mode` to be enabled at deploy time.

**To modify a page's UI**, edit the `.js` file and redeploy. No migration needed — the JS is served directly from the app.

**To add a new page:**
1. Create the directory and files under `admin_panel/admin_panel/page/{page_name}/`
2. Add an entry to the `pages` list in `admin_panel/setup.py`
3. Deploy and run `bench migrate`

#### Fixtures

Only `Workspace` and `Client Script` records are managed as fixtures — these are configuration records created through the ERPNext UI that have no other home in the app source tree.

To update them after making UI changes:
```bash
bench --site {site} export-fixtures --app admin_panel
```

This updates `admin_panel/fixtures/workspace.json` and `admin_panel/fixtures/client_script.json`.

### Releasing

Releases are versioned with git tags and published as a multi-arch Docker image (`brh28/frappe-flash`).

**Local release flow:**
```bash
./release.sh <major|minor|patch>
```
This bumps the version from the last git tag, creates a new tag, pushes it to the remote, and builds and pushes the Docker image.

**CI flow:**

A push of a version tag (e.g. `v1.2.0`) triggers CI, which runs `ci.sh` directly to build and push the image. `release.sh` is not involved.

**Version bump guide:**
- `patch` — bug fixes
- `minor` — new features
- `major` — breaking changes

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/admin_panel
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
