#!/usr/bin/env sh
set -eu

base_url=${1:-http://127.0.0.1:8080}
output_dir=${2:-.test-output}
mkdir -p "$output_dir"

assert_status() {
    expected=$1
    url=$2
    actual=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$url")
    if [ "$actual" != "$expected" ]; then
        printf 'Expected HTTP %s from %s, got %s\n' "$expected" "$url" "$actual" >&2
        exit 1
    fi
}

assert_status 200 "$base_url/jbrowser/"
assert_status 200 "$base_url/jbrowser/app/"
assert_status 200 "$base_url/jbrowser/bundles/"
assert_status 200 "$base_url/jbrowser/bundles/example-project/"
assert_status 200 "$base_url/jbrowser/bundles/example-project/demo.jbrowse/config.json"
assert_status 200 "$base_url/jbrowser/bundles/example-project/demo-two.jbrowse/config.json"
assert_status 200 "$base_url/jbrowser/bundles/second-run/results/jbrowse/other.jbrowse/config.json"
assert_status 200 "$base_url/jbrowser/bundles/top-level.jbrowse/config.json"
assert_status 200 "$base_url/jbrowser/bundles/Bundle%20root/nested.jbrowse/config.json"

curl --silent --show-error \
    --header 'Host: example.test:9999' \
    --dump-header "$output_dir/redirect.headers" \
    --output /dev/null \
    "$base_url/jbrowser"
grep -Eiq '^Location: /jbrowser/' "$output_dir/redirect.headers"

curl --silent --show-error "$base_url/jbrowser/" > "$output_dir/index.html"
grep -q 'Available configurations' "$output_dir/index.html"

curl --silent --show-error \
    --dump-header "$output_dir/landing-js.headers" \
    --output "$output_dir/app.js" \
    "$base_url/jbrowser/static/app.js"
grep -Eiq '^Cache-Control: no-cache' "$output_dir/landing-js.headers"

curl --silent --show-error "$base_url/jbrowser/app/version.txt" > "$output_dir/version.txt"
grep -qx '4.3.0' "$output_dir/version.txt"

curl --silent --show-error "$base_url/jbrowser/bundles/" > "$output_dir/bundles.json"
grep -q '"name":"example-project"' "$output_dir/bundles.json"
grep -q '"name":"top-level.jbrowse"' "$output_dir/bundles.json"
grep -q '"name":"Bundle root"' "$output_dir/bundles.json"

curl --silent --show-error "$base_url/jbrowser/bundles/example-project/" > "$output_dir/project.json"
grep -q '"name":"demo.jbrowse"' "$output_dir/project.json"
grep -q '"name":"demo-two.jbrowse"' "$output_dir/project.json"

curl --silent --show-error "$base_url/jbrowser/bundles/second-run/results/jbrowse/" > "$output_dir/second-run.json"
grep -q '"name":"other.jbrowse"' "$output_dir/second-run.json"

curl --silent --show-error \
    --header 'Range: bytes=0-9' \
    --dump-header "$output_dir/range.headers" \
    --output "$output_dir/range.body" \
    "$base_url/jbrowser/bundles/example-project/demo.jbrowse/reference/demo.fa"

grep -Eq '^HTTP/[0-9.]+ 206' "$output_dir/range.headers"
grep -Eiq '^Content-Range: bytes 0-9/' "$output_dir/range.headers"

curl --silent --show-error \
    --header 'Accept-Encoding: gzip' \
    --dump-header "$output_dir/config.headers" \
    --output "$output_dir/config.json" \
    "$base_url/jbrowser/bundles/example-project/demo.jbrowse/config.json"
if grep -Eiq '^Content-Encoding:' "$output_dir/config.headers"; then
    printf 'Bundle response unexpectedly used Content-Encoding\n' >&2
    exit 1
fi

printf 'jbrowser smoke test passed\n'
