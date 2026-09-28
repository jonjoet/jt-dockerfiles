# jbrowser

A deployment kit for serving multiple JBrowse 2 configurations from an existing nginx server under
`/jbrowser/`. It serves the JBrowse Web application and mounted data directly from nginx, preserving byte-range
requests for indexed genomic formats.

The landing page recursively discovers directories containing `config.json`, then groups configurations by the
folder that contains them. A QuickAlign output folder with several per-reference bundles therefore appears as one
section rather than being mixed into one flat table. The discovery remains generic: no QuickAlign manifest or
naming convention is required.

Bundles directly under the mounted root are grouped under `/`; real folder names remain unchanged.

## URL layout

| URL | Purpose |
|---|---|
| `/jbrowser/` | Searchable configuration index |
| `/jbrowser/app/` | JBrowse Web 4.3.0 |
| `/jbrowser/bundles/` | Read-only configuration and data tree |

The JBrowse app and data share an origin, so CORS is not required.

## Test with Docker Compose

The included fixture is used unless `JBROWSER_BUNDLES` points to another directory:

```bash
docker compose up --build -d
```

Open <http://127.0.0.1:8080/jbrowser/>. To test real configurations:

```bash
JBROWSER_BUNDLES=/absolute/path/to/bundles docker compose up --build -d
```

The mounted directory may contain projects and configurations at any depth. A directory becomes an entry when it
contains `config.json`; discovery then stops below that directory so it does not crawl the configuration's data
files. Do not nest one JBrowse configuration inside another.

Run the HTTP smoke test while the container is up:

```bash
./tests/smoke.sh
```

Stop the test deployment with:

```bash
docker compose down
```

`JBROWSER_BIND` and `JBROWSER_PORT` override the default `127.0.0.1:8080` binding.
Copy `.env.example` to `.env` to keep local overrides:

```bash
cp .env.example .env
```

`.env` and `.local-bundles/` are ignored so local deployment paths and test data are not committed.

## Deploy into an existing nginx server

The production paths used by [`nginx/jbrowser.locations.conf`](nginx/jbrowser.locations.conf) are:

```text
/srv/jbrowser/site/    landing-page files from site/
/srv/jbrowser/app/     extracted JBrowse Web release
/data/bundles/         dedicated read-only configuration tree
```

1. Copy `site/` to `/srv/jbrowser/site/`.
2. Download `jbrowse-web-v4.3.0.zip` from the
   [JBrowse 4.3.0 release](https://github.com/GMOD/jbrowse-components/releases/tag/v4.3.0), verify its SHA-256
   checksum, and extract its contents into `/srv/jbrowser/app/`.
3. Mount or bind the dedicated bundle tree at `/data/bundles/`. Keep this path read-only for nginx.
4. Include `nginx/jbrowser.locations.conf` inside the existing nginx `server` block.
5. Run `nginx -t`, then reload nginx.

Expected release checksum:

```text
a9d42417102ee088a1cbf85c6d857c1065d66984ea6c56f3115ef9dd56d76702  jbrowse-web-v4.3.0.zip
```

Edit the three `alias` paths in the include if the server uses different locations.

## nginx behavior

- nginx serves bundles directly; do not proxy them through Flask or another application server.
- `/jbrowser/bundles/` disables response gzip so `.bam` and BGZF-compressed files such as `.gff3.gz` retain their
  byte layout.
- nginx handles `Range` requests for static files and returns `206 Partial Content`.
- The unhashed landing-page files use `no-cache`, so index updates are visible immediately.
- Versioned JBrowse assets under `/jbrowser/app/static/` receive long-lived caching.
- The landing page fetches nginx JSON directory listings with `cache: no-store`, so copied configurations appear
  after a refresh without restarting nginx.
- The `^~` locations prevent generic regex locations elsewhere in the existing server from intercepting JBrowse
  assets or configuration files.

The mounted bundle root must be dedicated to published JBrowse data. JSON autoindex exposes its directory names,
and any file under the location is downloadable to users who can reach the server.

The include uses `expires` rather than location-level `add_header` directives so it does not discard headers
inherited from the existing server. If the existing server already defines more-specific `/jbrowser/` locations,
reconcile them before including this file.

## Current scope

This version groups configuration names and modification times by containing folder and provides JBrowse and raw
`config.json` links. QuickAlign manifest summaries, generated JBrowse Desktop configuration downloads,
ZIP/README links, and authentication are deliberately outside the current generic scope.
