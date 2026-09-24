# JBrowse default-view acceptance

`bash tests/browser/verify.sh` runs the focused bundle/resolver tests, builds a
small bundle with real GFF and indexed BAM data, and renders its unchanged
`config.json` in JBrowse Web **4.3.0**. This exercises the Desktop default-session
model through an actual browser. Native Windows/Desktop testing remains a user
acceptance step.

Build `quickalign:resolver-test` first using `tests/resolver/Dockerfile` (or run
`tests/verify.sh`). The browser runner builds the test-only image from
`tests/browser/Dockerfile` if missing. On this development host the equivalent
existing image can be reused:

```bash
BROWSER_TEST_IMAGE=cc_gcev/browser-test:4.3.0 bash tests/browser/verify.sh
```

Each run preserves `RUN.txt`, a source snapshot, image identities, pytest output,
render-state JSON, and a screenshot under the printed `.verification/` directory.
`windows-test.jbrowse/` is the portable bundle to copy onto Windows. Run
`resolve-local.cmd` there, then open `windows-test.local.jbrowse` in Desktop.

The Bash and PowerShell resolver fixtures each move twice, check every local
asset under the current root, check unchanged portable configuration, and check
empty/singleton/nested JSON arrays. Bash additionally covers POSIX-only control
characters and backslashes. Browser acceptance requires actual visible display
containers and completed annotation and alignment rendering; it does not accept
session JSON shape alone.

To exercise an actual deferred ZIP download from the installed Streamlit image,
first run `tests/verify.sh`, then pass its printed artifact directory:

```bash
BROWSER_TEST_IMAGE=cc_gcev/browser-test:4.3.0 \
  bash tests/browser/download_verify.sh /absolute/path/to/.verification/verify-RUN
```

Use an artifact directory from the current commit. The runner starts a temporary
service without exposing a host port, opens its completed warning result, checks
that rendering makes no archive request, clicks Download ZIP, and compares the
download to the completed disk export. It preserves logs, screenshot, archive,
and `RUN.txt`, then removes its service container. To use the repository's browser
image instead, omit `BROWSER_TEST_IMAGE` after building it with the JBrowse runner.
