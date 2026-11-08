# Changelog

## 0.2.34 — SMTP diagnostics and validation (2026-11-08)

- Validate complete sender and recipient email addresses before saving SMTP settings or sending mail.
- Rename the sender field to “Sender email address” / “Absender-E-Mail-Adresse”.
- Show actionable SMTP test errors for authentication, rejected addresses, connection, timeout and TLS failures without exposing credentials.
- Correct the LED socket integration test to work without root privileges in GitHub Actions.


## 0.2.33 — First stable public release (2026-11-08)

- Centralized monitoring for Linux single-board computers, with paired agents, a web dashboard, and optional Home Assistant integration.
- Optional SK6812 RGBW LED status indicators and configurable email notifications. WS2812/WS2812B hardware support remains unverified.
- English and German interface, with an account-specific language preference under User Settings.
- Authenticated password changes in User Settings, requiring the current password.
- Improved localization of configuration, device metrics, status messages, and dynamic interface elements.
- Fixed initial alignment of the navigation connector and its recalculation on layout, font, viewport, and language changes.
- Web controller runs as the restricted `sboc-web` user; a separate privileged LED service handles physical LEDs.
- First-admin setup uses a one-time local setup code, shown only during initial account creation.
- Documentation includes security limitations, noncommercial licensing, branding rights, and optional project support.
