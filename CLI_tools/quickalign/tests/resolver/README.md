# Resolver test image

This test-only image adds PowerShell to the ordinary quickalign test image. The
Microsoft PowerShell base is pinned by digest. PowerShell is not installed in
the product image.

From the `quickalign` directory, after building the normal `quickalign:tools`
test image:

```sh
docker build -f tests/resolver/Dockerfile -t quickalign:resolver-test .
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$PWD:/project" -w /project -e PYTHONPATH=/project/src \
  quickalign:resolver-test \
  pytest -q tests/integration/test_resolvers.py
```

The integration test creates a complete bundle with the pinned JBrowse CLI,
moves it beneath paths containing spaces, quotes, dollar signs, apostrophes,
ampersands, brackets, parentheses, semicolons, and non-ASCII characters, and
invokes each resolver from a different working directory. The POSIX case also
uses a literal backslash; Windows forbids that character in filenames and
PowerShell consequently treats it as a separator on Linux too.
