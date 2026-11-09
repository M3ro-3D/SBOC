# Release audit — 0.2.42

Source baseline: conversation-provided 0.2.41 archive, compared against conversation-provided 0.2.23 installer and release history. No live Git checkout was used as source.

## Covered by automated checks

- Python compileall of application and tests.
- Bash syntax validation of installer.
- JavaScript syntax of embedded login and dashboard scripts via Node.js.
- Configuration defaults, invalid inputs, mapping, operating modes, brightness/night priority.
- SQLite account bootstrap, login, session invalidation, password change, alarm transitions and acknowledgement.
- X25519/HKDF pairing, authenticated AES-GCM message exchange, key persistence, invalid code rejection.
- LAN address allowlist, email-address validation.
- Simulated controller HTTP: first-account setup code, wrong code, cross-origin POST rejection, login, protected API, invalid configuration, logout.
- Monitoring collection smoke test, startup catalog behavior, LED pixel validation and simulation.
- Update regression: Home Assistant token redaction and retention, configuration update, LED-only email suppression.
- Release archive: fresh extraction, required files, no TTF or secrets, repeated syntax and regression tests.

## Findings fixed in 0.2.42

- 0.2.40 dropped font acquisition and install progress; 0.2.41 restored these.
- 0.2.41 activated new application files before checking Python dependencies, with no rollback; 0.2.42 stages dependencies before activation and attempts service/program rollback on failure.
- Email notification path ignored the selected LED-only/web-only operating mode.
- Duplicate configuration entries and redundant mode validation.
- SQLite connections were committed but not closed, leaking file descriptors over time.
- Source release lacked adequate installation, security and license information.

## Explicitly unverified

- Full systemd/apt installer execution and rollback on target OS, including power interruption.
- GPIO12/GPIO13 SK6812 physical output and electrical power budget.
- Live upstream font downloads, third-party pip availability and integrity.
- Live SMTP and Home Assistant APIs.
- Chromium end-to-end browser rendering: loopback access is blocked by the current execution environment; embedded JavaScript syntax is checked.
- Full compatibility with all Linux SBC distributions and every historical configuration format.

The above limits mean this release is source-validated, not hardware-certified or guaranteed defect-free.

## 0.2.43 regression extension

Automated checks cover alarm and recovery email dispatch when Silent and Night modes are enabled. Hardware, SMTP delivery and network availability require real-device testing.
