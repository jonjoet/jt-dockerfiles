# quickalign (retired)

quickalign 0.1.0, the CLI and Streamlit tool that lived here, has been retired
and replaced by the standalone [Nextflow pipeline](https://github.com/jonjoet/quickalign).
The GUI will be rebuilt separately.

See [Differences from quickalign 0.1.0](https://github.com/jonjoet/quickalign#differences-from-quickalign-010)
for migration guidance.

The old code, including `examples/run.sh` and `examples/reads.tsv`, is preserved
at tag `quickalign-0.1.0`, commit `84977918770d47eb2d3a7c84cca7d3b3efb4277a`.
To restore it in a checkout of this repository:

```sh
git checkout quickalign-0.1.0 -- CLI_tools/quickalign
```
