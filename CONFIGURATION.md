# Configuration and local data

SBOC. separates application files from machine-specific configuration and state.

| Location | Purpose | Publish to Git? |
| --- | --- | --- |
| `/opt/sboc/sboc/` | Python application and static assets | Yes, as reviewed source |
| `/opt/sboc/venv/` | Locally installed Python packages | No |
| `/var/lib/sboc/config.json` | Controller configuration, device addresses, Home Assistant tokens | **Never** |
| `/var/lib/sboc/agent-trust.json` | Controller-side private agent keys | **Never** |
| `/var/lib/sboc-agent/pairing.json` | Local agent ID and current pairing code | **Never** |
| `/var/lib/sboc-agent/trust.json` | Private key for the paired controller | **Never** |
| `/var/lib/sboc/events.sqlite3` | Accounts, sessions, events, alerts, mail settings (potentially SMTP credentials) | **Never** |
| `/var/lib/sboc/events.sqlite3-wal`, `-shm` | SQLite runtime files | **Never** |
| `/etc/systemd/system/sboc-*.service` | Locally generated systemd services (`sboc-controller` as `sboc-web`, `sboc-led` as root, `sboc-agent` as `sboc-agent`) | Do not copy machine-specific files into the repository |

The controller receives its configuration path through `--config /var/lib/sboc/config.json` in the systemd unit. The SQLite database is created next to that config file. Updates replace application files in `/opt/sboc/sboc/` and preserve `/var/lib/sboc/`. The installer may migrate old state from `/var/lib/spoc` or `/var/lib/sbc-monitor` if no SBOC config exists yet.

**Important:** `.gitignore` only protects files not already tracked by Git. Before every public push inspect `git status`, `git ls-files`, and the commit history for credentials. Never commit real configuration, tokens, database dumps or logs. If a secret was committed, removing the file in a later commit does not erase it from history: rotate the credential and clean the repository history.

Agent pairing data is stored outside the application source with restricted file permissions. The agent service needs write access to `/var/lib/sboc-agent/`.

For backups, back up `/var/lib/sboc/` separately and securely; do not include it in source distributions.

## Interface languages and account settings

SBOC. is available in **English and German**. English is the default interface language. Signed-in users can switch between **English** and **Deutsch** under **User Settings → Language**. The preference is stored per account and is retained across sessions.

The **User Settings → Change password** form requires the current password and a matching new password of 12–256 characters. Changing the password invalidates the account's existing sessions; sign in again with the new password. Agent pairing is not affected.
