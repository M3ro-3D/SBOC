# SBOC. — Single Board Observation Computer

SBOC. monitors Linux single-board computers through a central controller. It provides a local web UI, authenticated and encrypted controller–agent communication, optional SK6812 RGBW LED status indication, Home Assistant OS system-monitor integration, and SMTP notifications.

> **LAN-only software.** SBOC. is intended for trusted local networks, not direct Internet exposure. Read [SECURITY.md](SECURITY.md) before installing.

## Features

- Monitor CPU temperature, CPU usage, memory, storage, network, and availability across Linux devices, with configurable monitoring of services and containers.
- View device status in the browser and optionally on two independent SK6812 RGBW LED strips.
- Connect Home Assistant OS for system-monitor metrics.
- Receive notifications and optional recovery messages by SMTP email. Silent Mode and Night Mode affect LEDs, **not email delivery**.
- Pair Linux agents with the controller using authenticated, encrypted communication.
- Choose English or German in per-account user settings.

## Architecture

- **Controller:** Python HTTP server, web UI, monitoring, email alerts; TCP port **8088**.
- **Agent:** lightweight Linux telemetry service; TCP port **8765**. Agent requests require pairing and encrypted communication; restrict the services to trusted networks.
- **Discovery:** mDNS through the `sboc-discovery` service.
- **Optional LED hardware:** two independent SK6812 RGBW GRBW strips, 10 LEDs each, on GPIO12 and GPIO13 on compatible Raspberry Pi hardware. Other platforms use LED simulation.
- **Home Assistant OS:** system-monitor sensor data via a Home Assistant long-lived access token.

## Requirements

- **Controller:** Debian-based Linux with Python 3, systemd, apt and network access during first installation. Raspberry Pi 3 Model B/B+ supports the configured SK6812 RGBW hardware; other platforms use LED simulation.
- **Agent:** Debian-based Linux with Python 3, systemd and the `cryptography` Python package. Agents are designed to be independent of Raspberry Pi hardware, but not every Linux board has been physically tested.
- **LED wiring:** two independent SK6812 RGBW GRBW strips, 10 pixels each, on GPIO12 and GPIO13 if hardware LEDs are enabled. Ensure an appropriate power budget and common ground.
- **Network:** trusted LAN; controller TCP 8088, agent TCP 8765. Neither port should be forwarded to the Internet.

## Installation

SBOC. runs on a **controller** (hosting the web interface) and optional **agents** (Linux devices to monitor). Install the same release package on each device, then choose its role when prompted. **No GitHub account, Git, or GitHub CLI is required.**

### 1. Download and install

Download the appropriate archive from [GitHub Releases](https://github.com/M3ro-3D/SBOC/releases) and copy it to your device. For the 0.2.43 archive, run:

```bash
tar -xzf SBOC-0.2.43.tar.gz
cd SBOC-0.2.43
sudo ./install.sh
```

On a fresh installation, select **1 — Controller** or **2 — Agent**. Existing installations are detected by their service files and updated in place. The installer reports seven steps, stages program files before activation and checks services. An unsuccessful activation attempts to restore previous program and service definitions; this does not replace a device-level backup. A reboot is normally not required.

The installer uses `apt` to install missing Debian dependencies, and `pip` for required Python dependencies. It may need Internet access for packages and fonts. The LED driver is installed for supported hardware; other controller platforms use simulated LEDs.

### 2. Open the controller interface

On another device on the **same trusted local network**, open:

`http://<controller-ip>:8088`

To find the controller IP address, run `hostname -I` on the controller. Do not forward port 8088 to the Internet: the web interface uses **unencrypted HTTP**.

### 3. Set up the administrator and connect devices

For a fresh controller installation, continue with [First-time administrator setup](#first-time-administrator-setup). To connect Linux agents, follow [Secure Agent Pairing](#secure-agent-pairing). Home Assistant OS uses its API instead of a Linux agent.

### Updating an existing installation

Download the new release archive from [GitHub Releases](https://github.com/M3ro-3D/SBOC/releases), extract it and run `sudo ./install.sh` from the extracted release directory. Use the actual filename and version of that release; the commands above refer specifically to 0.2.43.

The installer detects the existing role and preserves runtime data in `/var/lib/sboc/` (controller) and `/var/lib/sboc-agent/` (agent). Existing accounts and agent pairing are intended to remain intact. The installer attempts rollback if activation fails, but this is not a full system backup.

## First-time administrator setup

On a **new controller installation**, run `sudo sboc-setup-code` via SSH on the controller to obtain the one-time administrator setup code. Enter it when creating the first account. The setup code is only needed for initial account creation; existing accounts and sessions are preserved on upgrades.

## Secure Agent Pairing

The six-digit code is temporary and is not a permanent access token. Do not share it publicly.

1. Install SBOC. on the controller and agent devices.
2. Run `sudo sboc-pairing-code` via SSH on each agent.
3. In the controller, open the device setup and select **Pair** for an existing agent, or add a discovered agent.
4. Enter the six-digit pairing code and complete pairing. The agent creates a new pairing code after successful pairing.

Pairing an agent again replaces its previous controller key. To switch controllers, pair the agent again. Home Assistant OS devices do not require an agent pairing code; they continue to use the Home Assistant access token.

**Security boundary:** Agent telemetry is protected using authenticated AES-GCM after pairing. The SBOC web interface and HTTP connections to Home Assistant remain unencrypted. See [SECURITY.md](SECURITY.md).

## Configuration and persistent data

- `/var/lib/sboc/`: controller configuration, accounts, event database, trusted agent keys and SMTP settings.
- `/var/lib/sboc-agent/`: agent identity, pairing state and controller trust key.
- `/opt/sboc/`: installed program and Python environment; not the source repository.

Never commit runtime data, Home Assistant tokens, SMTP passwords or other secrets to GitHub.

The Home Assistant URL is entered with scheme and port, for example `http://homeassistant.local:8123`. Create a long-lived access token under **Home Assistant → User profile → Security**. See the [official Home Assistant authentication instructions](https://www.home-assistant.io/docs/authentication/).

Agent and Home Assistant connections are restricted to validated local-network destinations. Redirects and proxies are disabled for those connections; see [SECURITY.md](SECURITY.md) for limitations.

## Interface languages and account settings

SBOC. is available in **English and German**. English is the default interface language. Signed-in users can switch between **English** and **Deutsch** under user settings. The preference is stored per account.

Changing a password requires the current password and a matching new password of 12–256 characters. Changing it invalidates existing account sessions; agent pairing is unaffected.

## Fonts and external dependencies

Sora is a third-party font from the [Sora font project](https://github.com/sora-xor/sora-font), licensed under the SIL Open Font License 1.1. The installer reuses existing local font files or downloads the four required TTF weights. Font binaries are **not** included in the source archive. First installation requires network access unless all dependencies and fonts are already available.

## Updates and service commands

The LED service exists only on controllers with compatible LED hardware.

```bash
sudo systemctl status sboc-controller sboc-agent sboc-led
sudo systemctl restart sboc-controller
sudo systemctl restart sboc-agent
sudo journalctl -u sboc-controller -n 100 --no-pager
```

Agent service/container discovery refreshes when the agent service restarts.

## Project status and validation

SBOC. is under active development. Automated tests cover core configuration, accounts, pairing and encryption, selected monitoring and LED behavior, and HTTP authentication. They cannot replace physical tests of GPIO, installation on every supported board, external SMTP, Home Assistant or hardware-specific systemd behavior. See [TESTING.md](TESTING.md) and [SECURITY.md](SECURITY.md).

## License

**SBOC. is source-available, not OSI-approved open-source software.** Private non-commercial use is permitted. Business, commercial and internal organizational use requires prior explicit permission from the copyright holder. See [LICENSE](LICENSE) for the applicable terms. M3ro-3D retains exclusive rights to M3ro logos and branding.

## A Note on AI-Assisted Development

**SBOC. is vibe-coded software.** Let's be upfront about that.

The author has ideas, a sense for practical software, and a passion for simple, useful interfaces. What he doesn't have is extensive programming experience, particularly in the languages used to build this project.

That's where AI comes in.

The author sees AI-assisted programming as using a tool, much like an image editor, a 3D modeling application, or a sound generator. The ideas, requirements, design decisions, and overall direction come from a human. AI helps turn them into working code.

**Knowing how to design something and knowing what makes a good design are not quite the same thing.**

AI has access to an enormous amount of theoretical knowledge about design principles, user experience, and interface development. But knowing the rules doesn't necessarily mean having the human intuition for aesthetics, simplicity, and what actually feels right to use.

An interface can follow every design guideline and still feel cluttered, confusing, or unnecessarily complicated. Recognizing that difference requires human judgment, taste, and real-world experience.

In SBOC., AI helps with implementation, but the final decisions about appearance, usability, and whether something is genuinely useful remain firmly in human hands.

**And there's a lot more to building software than generating code.**

Testing, troubleshooting, refining features, and making everything work reliably in the real world still require considerable time and effort. AI can help with these tasks, but it has limited access to actual hardware, real-world environments, and the countless little things that can go wrong outside a development environment.

SBOC. has gone through numerous iterations, tests, failures, fixes, and releases to get where it is today. And that process continues.

It's not a matter of telling an AI, *"Build me a monitoring tool,"* waiting five minutes, and walking away with a finished product. If only it were that simple.

None of this means the software is automatically good or bad. Nor does it mean that AI-generated code is free from bugs, security vulnerabilities, or questionable design decisions.

**The point of this disclaimer isn't to make excuses. It's to be transparent about how this software was created and the work that goes into it.**

Evaluate SBOC. based on what it does, how well it works, and whether it meets your needs.

Use it if you find it useful. Don't use it if you don't — whether because it doesn't meet your needs or because you're simply not comfortable using AI-generated software. That's a perfectly reasonable choice.

**Either way, I wanted you to know how SBOC. came to be, what went into making it, and who's behind the decisions. The rest is up to you. Make your own judgment.**

## ☕ Powered by Coffee

Some projects run on electricity. Mine run on coffee. ☕

Coffee is my fuel, and quite a few cups have already gone into building SBOC.

If you enjoy this project and would like to keep the caffeine flowing, I'd be happy about a little contribution to my coffee fund.

[![Buy Me a Coffee](https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png)](https://buymeacoffee.com/m3ro)

*No pressure, just coffee. ❤️*
