# Contributing

Thanks for your interest in SBOC. Contributions and issue reports are welcome.

Before submitting code, open an issue describing the problem and proposed change. Keep controller/agent responsibilities clear, avoid introducing implicit triggers, and do not include runtime configs, credentials, or personal data.

For code changes, include reproduction steps, tests where possible, and documentation for user-visible behavior. Verify Python syntax and run `bash -n install.sh` before opening a pull request. Security-sensitive changes should be discussed privately using the repository's vulnerability reporting feature if enabled.

SBOC. is licensed under the PolyForm Noncommercial License 1.0.0. Please review [LICENSE.md](LICENSE.md) before contributing. Do not assume that the software is licensed for commercial use.


## Required bilingual UI coverage

Every UI change must be implemented in both English and German and tested in both languages before release. This includes static and dynamic text, errors, dialogs, help text, and accessibility labels. Mixed-language screens are release-blocking defects.
