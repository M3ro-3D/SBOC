## 0.2.43 — Silent/Night mail independence regression tests (2026-11-09)

- Confirmed that Silent Mode and Night Mode only govern LED presentation and do not suppress configured alarm or recovery emails.
- Added automated tests for alert and recovery emails with both modes enabled, and for mail-only operation.
- No change to existing alert dispatch behavior.

# Changelog

## 0.2.42 — source audit and release hardening (2026-11-09)

- Restore installer-managed Sora font acquisition without bundling font binaries.
- Stage application files and Python dependencies before activation; attempt rollback of program and service units if activation fails.
- Restore installation progress and verify service startup.
- Correctly disable automatic alert emails when operating mode is LED-only or web-only.
- Remove duplicate configuration defaults and validation logic.
- Close SQLite connections deterministically to prevent descriptor accumulation.
- Add automated regression and HTTP integration tests, licensing, deployment/security documentation.

## 0.2.41

- Restore seven visible installer steps and Sora font downloads from earlier releases.

## 0.2.40

- Mobile LED editor positioning and close interactions; preserve previous alarm and acknowledgement features.
