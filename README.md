# SBOC. — Single Board Observation Computer

SBOC. monitors Linux single-board computers through a central controller. It provides a local web UI, authenticated and encrypted controller–agent communication, optional status LEDs, Home Assistant OS system-monitor integration, and SMTP notifications.

## Requirements

- Controller: Debian-based Linux with Python 3, systemd, apt and network access during first installation. Raspberry Pi 3 Model B/B+ supports the configured SK6812 RGBW hardware; other platforms use LED simulation.
- Agent: Debian-based Linux with Python 3, systemd and the `cryptography` Python package. The agent is designed to be independent of Raspberry Pi hardware, but not every Linux board has been physically tested.
- Two independent SK6812 RGBW GRBW strips, 10 pixels each, on GPIO12 and GPIO13 if hardware LEDs are enabled. Ensure an appropriate power budget and a common ground.
- Trusted LAN; controller TCP 8088, agent TCP 8765. Neither port should be forwarded to the Internet.

## Installation / update

Download the release archive, then:

```bash
tar -xzf SBOC-0.2.43.tar.gz
cd SBOC-0.2.43
sudo ./install.sh
```

On a fresh installation, choose **1) Controller** or **2) Agent**. Existing installations are detected by their service files and updated in place. No reboot is normally required. The installer reports seven steps and checks the services. Program files are staged before activation, and an unsuccessful activation attempts to restore the previous program and service definitions. This is not a replacement for a device-level backup.

**First controller setup:** open `http://<controller-ip>:8088` on your trusted LAN. Run `sudo sboc-setup-code` on the controller and enter that code to create the first administrator account. The setup code is only needed for initial account creation.

**Agent pairing:** run `sudo sboc-pairing-code` on the agent, then pair it from the controller UI. Pairing replaces the previous controller key; the agent generates a new six-digit pairing code after successful pairing.

**Services:** `sboc-controller`, `sboc-agent`, `sboc-discovery` (mDNS), and `sboc-led` on compatible LED hardware. Check with `sudo systemctl status sboc-controller sboc-agent` and `sudo journalctl -u sboc-controller -n 100 --no-pager`.

## Persistent data

- `/var/lib/sboc/`: controller configuration, accounts, event database, trusted agent keys, SMTP settings.
- `/var/lib/sboc-agent/`: agent identity, pairing state, controller trust key.
- `/opt/sboc/`: installed program and Python environment; not the source repository.

Updates must not erase persistent data. Never commit the contents of `/var/lib/sboc*` or secrets to GitHub.

## Fonts and external dependencies

Sora is a third-party font from the [Sora font project](https://github.com/sora-xor/sora-font), licensed under the SIL Open Font License 1.1. The installer reuses existing local font files or downloads the four required TTF weights. Font binaries are **not** included in this source archive. The installer also installs missing Debian packages and, on the controller, Python dependencies through pip when necessary. First installation therefore requires network access unless all dependencies and fonts are already present.

## Security and license

The browser UI uses HTTP, **not HTTPS**. Credentials and new Home Assistant tokens can traverse the local network without TLS. Use only a trusted LAN; never expose the web UI or agent port publicly. Agent telemetry uses authenticated AES-GCM after pairing. See [SECURITY.md](SECURITY.md).

**Source-available, non-commercial license.** Private non-commercial use is permitted; commercial or internal organizational use requires prior explicit permission from the copyright holder. See [LICENSE](LICENSE). This project is not offered as an OSI-approved open-source license.

## Validation status

Automated tests cover core configuration, accounts, pairing and encryption, selected monitoring and LED behavior, and HTTP authentication. They cannot substitute for physical tests of GPIO, real installations on all supported boards, external SMTP, Home Assistant or hardware-specific systemd behavior. See [TESTING.md](TESTING.md).
