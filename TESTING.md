# Testing

From the extracted release directory:

```bash
python3 -m compileall -q sboc tests
python3 -m unittest discover -s tests -v
bash -n install.sh
```

`tests/test_http.py` starts a simulated controller on loopback and tests first-account creation, authentication, session expiry via logout, CSRF origin validation, and configuration validation. `tests/test_core.py` covers configuration, LED bounds, monitoring, SQLite alerts and accounts, encrypted pairing and other behavior.

Limitations: real GPIO output, live Sora download, Debian package installation, systemd service activation, external SMTP and Home Assistant require target-system testing. A fresh tar extraction must be tested independently of the working tree. The browser's JavaScript syntax can be checked with Node.js; interactive browser rendering requires a browser environment that permits local loopback access.
