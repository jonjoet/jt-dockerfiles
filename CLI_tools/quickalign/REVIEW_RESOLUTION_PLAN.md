# quickalign review resolution plan

Written by GPT-6 on 2026-09-24. **Planning only; these fixes are not implemented.**

Reviewed implementation: `20b98c36e9aa4a6733f58b9e520f1d5fa840bd59`.
This document records the user's decisions following Claude's review and
supersedes conflicting validation, resolver, and download details in
`IMPLEMENTATION_PLAN.md`. Other original scope decisions remain in force.

Deferred findings: https://github.com/jonjoet/jt-dockerfiles/issues/8.
Do not pull that backlog into this fix pass without a new scope decision.

## Intended functionality and scope

Create a portable output directory containing the reference, annotation,
aligned BAMs, indexes, JBrowse configuration, and local resolver launchers.
The user runs the resolver and opens the generated `.jbrowse` file in Desktop
to see a useful initial view. A bundle means this previously created output
directory; a ZIP is an optional archive of that directory.

The results list should show completed jobs, warnings, and where their outputs
are located. It is not a background integrity scanner. Listing results,
refreshing the page, restarting the app, or requesting export must not cause
automatic SHA-256 rereads of BAMs. Keep hashes computed once during creation
as manifest provenance, following gcev; do not rehash to compare them during
normal operation. No verification-stamp database, checksum cache redesign,
single-flight hashing service, or new Verify UI is needed.

Real outputs may contain many gigabytes of BAM data. Preserve mounted-output
retrieval for large results and disk-based ZIP export. Browser download remains
an optional convenience for files below the configured size threshold; page
rendering must never read an archive's payload. A deferred Streamlit callback
does not provide streamed multi-gigabyte HTTP downloads. Adding such a server
is outside this pass and would change the original product scope.

Native Windows/Desktop testing will be performed by the user. Agent work
should produce a concrete bundle for that test without investigating
speculative Windows issues or requiring a new Windows test environment.

## 1. Reuse gcev's JBrowse and resolver approach

Reference checkout: `/home/qbk/qbk-code/cc_gcev`, inspected clean at
`1046c67663777490f882ff1afa811eff07458707`.
Primary source: `bin/build_jbrowse_bundle.mjs`, especially `buildConfig`,
`localizeUris`, and `writeResolvers`. Supporting recipes:
`tests/integration/check_jbrowse_resolvers.sh`,
`tests/integration/validate_local_jbrowse.ps1`,
`tests/browser/jbrowse_bundle_smoke.mjs`, and
`docs/sessions/05-jbrowse2-bundle.md`.

The user confirms this project already produces working Desktop bundles.
Use its source as the reference whenever resolver behavior is unclear.

- Replace quickalign's singular `defaultSession.view` with Desktop's
  `defaultSession.views` array and track-ID-based initialization. gcev uses a
  multi-assembly `LinearSyntenyView`; quickalign needs a single-assembly
  `LinearGenomeView`, a bounded initial locus, annotation, and the first BAM
  visible. Keep all remaining BAM tracks available for selection. Adapt this
  view-specific part rather than copying synteny state.
- Ensure initialization creates actual visible track displays, rather than
  accepting JSON shape alone as proof of a useful rendered view.
- At build time, convert relative file locations to `LocalPathLocation` entries
  containing a quickalign root token in `local.template.jbrowse`. Perform this
  after text-index generation so index locations are included. Keep the
  portable `config.json` unchanged and retain safe relative-path validation.
- Adapt gcev's Bash and PowerShell token-substitution resolvers. Each derives
  the current bundle root from its own script location, JSON-escapes that root,
  and writes the generated local configuration through a temporary file.
  The Bash script needs no Python installation. PowerShell only JSON-encodes
  the root scalar, avoiding recursive JSON/array reserialization.
- Reuse gcev's `.cmd` launcher: prefer `pwsh`, fall back to `powershell.exe`,
  and locate the sibling script through `%~dp0`. Keep quickalign's documented
  `resolve-local.*` filenames.
- Update validation and fixtures: the localized template will intentionally
  differ from portable config, replacing the current equality requirement.
  Generated local configs contain the user's current absolute bundle root;
  this is necessary for Desktop and distinct from leaking original input paths.
- Update README and generated bundle instructions to describe the actual
  resolver workflow and prerequisites.

Acceptance: verify the default view initializes annotation and a BAM using
the pinned JBrowse version, borrowing gcev's relevant smoke recipe. Resolve a
bundle from paths containing spaces and JSON/shell-sensitive characters;
move it a second time and rerun the resolver. Check every generated local
location resolves under the new root and the portable config is unchanged.
Provide the resulting bundle's exact path for the user's Windows test.

## 2. Remove original absolute paths from portable metadata

In gcev, `copyReadEvidence` stages known relative filenames and returns
presence flags; its manifest inventory uses bundle-relative paths. It does
not carry the raw-input display fields responsible for quickalign's leak.
Reuse that separation of execution paths from exported presentation data.

- In `inputs.py`, normalize default display names for TSV read groups to
  basenames, matching other entry points. Retain resolved source paths where
  needed to open files and record private job execution metadata.
- Trace those values through config, manifest, bundle README/warnings, CLI
  summaries, and UI. Fix the producer rather than relying on display redaction.
- Preserve explicit user labels and the mapping from read groups to tracks.
  Do not conflate this fix with the deferred choices about label casing or
  relative `@PG` provenance.

Acceptance: build from a TSV containing distinctive absolute source paths,
including paired inputs and a warning-producing input. Assert that generated
portable text/JSON metadata contains the expected basenames and labels but
none of those source-directory prefixes. Confirm execution still opens the
correct files. The portable resolver template must contain only its root token,
not the build machine's root.

## 3. Make completed-output discovery and downloads inexpensive

Affected paths include `bundle.py` validation, `jobs.py` publication/discovery/
export, and `ui/app.py` result rendering. Treat these as one integrated change.

- Separate creation-time output checks from lightweight availability checks.
  Validate schema, safe relative inventory paths, required files, and tool
  outputs before atomic publication. Compute each recorded checksum once when
  creating the manifest; eliminate subsequent full checksum passes, including
  the post-rename cache miss.
- For existing jobs, use bounded job/manifest/config metadata and required
  file existence/size checks. Do not open BAM payloads, reconstruct a strict
  recursive directory inventory, or reject a completed result merely because
  `.DS_Store` or a resolver-generated file was added. Keep traversal and symlink
  protections for files the application actually reads or exports.
- Preserve the completed-status/publication contract: an arbitrary directory
  is not a completed job. Report known missing/invalid required outputs clearly.
  Lightweight checks intentionally do not detect same-size payload corruption;
  do not describe them as fresh checksum verification.
- Remove the full-hash cache and avoid calling availability validation twice
  when rendering the same result. Use manifest sizes for the result's size
  display/threshold decision rather than another recursive walk.
- Replace the eager open-file `st.download_button` data argument with a deferred
  callback supported by the pinned Streamlit version. Check archive containment,
  regular-file status, and actual size again when clicked; read at most the
  configured limit plus a rejection sentinel so growth cannot bypass the cap.
  Use `on_click="ignore"` where appropriate. Only a bounded, explicitly clicked
  small download may enter application memory.
- Keep large bundles and ZIPs accessible through the mounted output directory
  with clear relative paths/instructions. Preserve chunked disk ZIP creation
  and Zip64 support. Existing ZIP CRC verification is an explicit export-time
  operation, not a results-page operation; avoid introducing another checksum
  scan ahead of it. Export failure must not invalidate the completed bundle.

Acceptance: instrument payload reads/checksum calls and list more than 64
completed jobs twice, including an app restart. Assert no BAM payload reads or
hashing in discovery/rendering and no ZIP payload reads before a download click.
Assert no repeated creation-time checksum passes. Cover benign extra files,
missing required files, and unsafe tracked paths. Exercise both bounded small
downloads and over-limit rejection, including growth between render and click.
Use a sparse multi-gigabyte archive placeholder for the metadata-only rejection
test; do not label it a valid ZIP or an actual large BAM/export acceptance run.

## 4. Correct FASTQ EOF handling

- A single/unpaired input ending in a bare `@` without a newline is an
  incomplete final record: preserve preceding complete records and emit the
  established truncation warning instead of failing during mate-name parsing.
- Accept trailing blank lines at EOF, including the paired validation pass.
  Buffer/look ahead to distinguish an EOF suffix from malformed blank lines
  inside the FASTQ stream. Do not silently skip interior malformed records.
- Keep paired reads strict about incomplete records, mate identity, and counts.
  A bare `@` fragment in paired data is still a failure. Do not turn malformed
  complete headers, CRC failures, or detected DEFLATE corruption into warnings.
- Preserve the existing failure for inputs with no usable complete reads.
  Update documented tolerance to match these precise boundaries.

Acceptance: focused plain/gzip single and paired fixtures covering bare `@`
at EOF, an invalid complete empty header, trailing blank suffixes, interior
blank lines, unequal mates, and successful recovery of preceding single reads.
Assert both output records and warning/failure behavior. Other gzip detection
limits and the broader failure-injection matrix remain in issue #8.

## Implementation and next-session handoff

1. Confirm the checkout, current SHA, clean/dirty state, and implementer role
   through agmsg before edits. At planning time Codex held implementer and
   Claude held reviewer. Do not alter the preexisting untracked `.claude/`.
2. Follow the user's authorized parallel exception: GPT-5.6 Sol workers in
   isolated Git worktrees; GPT-6 Astra for supervision and difficult integration.
   Keep exactly one integrator writing the main checkout. Git worktrees need
   no beta feature. Check the actual worktree list before creating any.
3. Suggested ownership: one Sol worker handles the JBrowse/resolver change in
   `bundle.py` and resolver fixtures; a second handles `inputs.py` display/FASTQ
   changes and focused input tests. Astra reviews semantics while the integrator
   prepares the jobs/UI change. Integrate the bundle work before changing its
   validation interface; do not have two writers modify that interface at once.
4. Update README/examples with each behavioral change. Run focused checks,
   then the existing Docker suite once on the integrated implementation and an
   installed-image CLI/UI smoke appropriate to these fixes. Do not turn deferred
   test improvements into a prerequisite for this pass.
5. Every test/probe run starts with RUN.txt recording commit, dirty state, UTC
   start time, and purpose. Keep Docker bind mounts project-local, preserve
   outputs, and record exact artifact paths in the implementation handoff.
   Retest any evidence invalidated by subsequent changes.
6. Give Claude the exact integrated SHA and artifact paths for independent
   review. Include the user-test bundle path. Commit messages name the writing
   model. Remove worker worktrees only after integration and confirming their
   changes are preserved; retain verification artifacts. Do not discard unmerged
   work or delete the user's files to make cleanup easier.

Historical evidence applies only to the reviewed baseline. Its artifacts are
under `/home/qbk/qbk-code/jt-dockerfiles/CLI_tools/quickalign/.verification/final-20b98c3/`:
`RUN.txt`, `pytest.log`, `junit.xml`, `cli.log`, `compose-inspect.json`,
`browser-result.txt`, `browser-checks.txt`, and `deployment-checks.txt`.
The historical CLI bundle is `cli-outputs/mixed/reference.jbrowse/` under that
same directory. Verify existence and RUN.txt before citing any of these;
generate fresh evidence for the fixes. They do not establish corrected Desktop
default-view behavior.

Suggested resume request:

> Implement REVIEW_RESOLUTION_PLAN.md, keeping issue #8 deferred. Confirm roles
> through agmsg, use GPT-5.6 Sol workers in isolated worktrees and GPT-6 Astra
> for supervision/tricky work, with one main-checkout integrator. Use gcev as
> the resolver reference. I will test Windows. Preserve and identify artifacts,
> obtain independent review, and close integrated worktrees when appropriate.
