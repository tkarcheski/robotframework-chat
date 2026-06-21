# DB Simplification Plan

This document records the v2 database schema decisions and amendments.

---

## Schema Freeze (v2 direction)

The v2 database schema direction is to replace the ad-hoc table additions from v1
with a clean, normalized schema as described in issue #377. Until that unified
schema lands, the rule is: new domain tables may be added without a formal freeze
exception, subject to the `CLAUDE.md` rule against `Optional` on DB dataclass
fields.

---

## Amendment: Dialog Tables Ratified (2026-06-16)

**Decision (owner, 2026-06-16):** `dialog_recordings` and `dialog_turns`
(merged via PR #409, issue #354) are ratified as sanctioned extensions to the
v2 schema. These tables are in-scope for the unified models work in #377 but do
not require migration or reversion.

**Ruling:** "Keep the dialogue tables."

**Context:** PR #409 merged `dialog_recordings` + `dialog_turns` into
`src/rfc/harness_db.py` while the CLAUDE.md v2 direction had declared the legacy
DB schema frozen pending #377. Issue #428 was filed to resolve whether the tables
should be ratified as a schema amendment or planned for migration. The owner ruled
Option A: ratify as an amendment.

**What this unblocks:** downstream work referencing dialog tables (e.g., #437
end-to-end coverage and the dialog import stack) is no longer schema-blocked.
