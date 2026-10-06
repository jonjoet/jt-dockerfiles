import fs from 'fs';

const NativeURL = URL;
const html = fs.readFileSync(new URL('../fasta_gff_combiner.html', import.meta.url), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];

const store = {};
function fakeEl() {
  return {
    listeners: {},
    classList: { add(){}, remove(){}, toggle(){} },
    addEventListener(type, fn){ this.listeners[type] = fn; },
    style: {},
    innerHTML: '',
    textContent: '',
    value: '',
    checked: false,
    disabled: false,
    dataset: {},
    querySelector(){ return null; },
    focus(){},
    select(){},
  };
}
for (const id of ['fastaInput','gffInput','fastaBox','gffBox','fileChips','workspace',
  'emptyState','warnBanner','ambiguityPanel','statsBar','searchBox','autoDisambig',
  'namespaceGffIds','namespaceInfo','tableHead','tableBody','outputsSummary','exportInfo','exportBtn']) store[id] = fakeEl();

let alerts = [];
let confirms = [];
globalThis.document = {
  getElementById: id => store[id] || (store[id] = fakeEl()),
  createElement: () => ({ click(){}, style: {} }),
  body: { appendChild(){}, removeChild(){} },
};
globalThis.alert = message => alerts.push(message);
globalThis.confirm = message => { confirms.push(message); return true; };
globalThis.URL = { createObjectURL: () => 'blob:', revokeObjectURL(){} };

const T = eval(script + `
;({
  parseFasta, parseFastaDetailed, parseGff, parseGffDetailed, parseAttributes,
  loadFastaFiles, loadGffFiles, resolveExportNames, collisionInfo, buildFasta,
  buildGff, crc32, makeZip, addOutput, toggleMember, featureCount,
  featureEntriesForRecord, ambiguousGffMatches, assignGffMatch, orphanSeqids,
  outputBlockers, outputWarnings, featureIdConflicts, maxSequenceLength,
  gffNamespacePlan, relationshipReferenceIssues, rewriteFeatureAttributes,
  downloadOutput, downloadAllZip,
  get records(){ return records; },
  get outputs(){ return outputs; },
  get gffSources(){ return gffSources; },
  get maxZipBytes(){ return MAX_ZIP_BYTES; },
  set autoDisambiguate(v){ autoDisambiguate = v; },
  set namespaceFeatureIds(v){ namespaceGffIds = v; },
  resetState(){
    loadGeneration++;
    records = []; outputs = []; gffSources = []; gffAssignments = new Map();
    fastaFileNames = []; recordSeq = 0; outputSeq = 0; fastaSourceSeq = 0; gffSourceSeq = 0;
    sortCol = 'length'; sortDir = -1; autoDisambiguate = false; namespaceGffIds = false;
    namespacePlanCache = null;
    loadGeneration = 0; fastaLoadChain = Promise.resolve(); gffLoadChain = Promise.resolve();
  },
  setDownloadCapture(fn){ triggerDownload = fn; },
  setZipCapture(fn){ makeZip = fn; triggerDownload = () => {}; },
});`);

let pass = 0;
let fail = 0;
function check(name, condition, extra = '') {
  if (condition) {
    pass++;
    console.log('  ✓', name);
  } else {
    fail++;
    console.log('  ✗ FAIL', name, extra);
  }
}
const file = (name, text) => ({ name, text: async () => text });
const headers = text => (text.match(/^>/gm) || []).length;
const featureLines = text => text.split('\n').filter(line => line && !line.startsWith('#'));

console.log('\n[input validation]');
let parsedFa = T.parseFastaDetailed('\uFEFF>a\rAC GT\r>b\rNN', 'x.fa', 'f1');
check('BOM and CR-only FASTA preserve records', parsedFa.records.length === 2);
check('sequence whitespace is normalized and reported', parsedFa.records[0].sequence === 'ACGT' && parsedFa.warnings.some(w => w.includes('line 2')));
check('empty FASTA identifier is rejected', T.parseFastaDetailed('>\nAC').errors.some(e => e.includes('identifier')));
let parsedGff = T.parseGffDetailed('a\ts\tgene\t1\t2\t.\t+\t.\tgene_id "x";');
check('GTF content is rejected', parsedGff.errors.some(e => e.includes('GTF')));
parsedGff = T.parseGffDetailed('a\ts\tgene\t1\t2\t.\t+\t.\tgene_id "A=B";');
check('inconclusive GTF-like attributes warn', parsedGff.errors.length === 0 && parsedGff.warnings.length === 1);
parsedGff = T.parseGffDetailed('a\ts\tgene\t1\t2\t.\t+\t.\tNote="quoted";ID=x');
check('ordinary quoted GFF3 attribute is accepted', parsedGff.errors.length === 0 && parsedGff.warnings.length === 0);
parsedGff = T.parseGffDetailed('a\ts\tgene\t1\t2\t.\t+\t.\tID=x;Note=has "quoted" text');
check('quoted phrase inside GFF3 free text is silent', parsedGff.errors.length === 0 && parsedGff.warnings.length === 0, parsedGff.warnings);
check('malformed GFF row is rejected with line number', T.parseGffDetailed('a\tbad').errors[0].startsWith('line 1:'));
check('invalid phase is rejected', T.parseGffDetailed('a\ts\tCDS\t1\t2\t.\t+\t9\tID=x').errors.some(e => e.includes('phase')));

console.log('\n[source-aware annotation matching]');
T.resetState();
await T.loadFastaFiles([
  file('a.fasta', '>chr1\nAAAA'),
  file('b.fasta', '>chr1\nCC'),
]);
await T.loadGffFiles([file('annotations.gff3', 'chr1\ts\tgene\t1\t4\t.\t+\t.\tID=g1')]);
let ambiguity = T.ambiguousGffMatches()[0];
check('duplicate seqid creates one explicit ambiguity', ambiguity && ambiguity.candidates.length === 2);
const out = T.outputs[0];
for (const record of T.records) T.toggleMember(out.id, record.id, true);
check('unresolved annotation assignment blocks affected output', T.outputBlockers(out).some(x => x.includes('ambiguous')));
const aRecord = T.records.find(record => record.sourceFile === 'a.fasta');
const bRecord = T.records.find(record => record.sourceFile === 'b.fasta');
T.assignGffMatch(ambiguity.key, aRecord.id);
check('resolved feature attaches to chosen record only', T.featureCount(aRecord) === 1 && T.featureCount(bRecord) === 0);
T.autoDisambiguate = true;
let names = T.resolveExportNames();
let builtGff = T.buildGff(out, names);
check('one input feature emits exactly once', featureLines(builtGff).length === 1, builtGff);
check('chosen feature seqid follows chosen record export name', featureLines(builtGff)[0].startsWith(names[aRecord.id] + '\t'));
check('feature is not copied out of bounds to second record', !builtGff.includes(names[bRecord.id] + '\ts\tgene'));

console.log('\n[name collision safety]');
T.autoDisambiguate = false;
check('duplicate final names block output', T.outputBlockers(out).some(x => x.includes('duplicate final')));
alerts = [];
let downloadCount = 0;
T.setDownloadCapture(() => { downloadCount++; });
T.downloadOutput(out.id, 'fasta');
check('individual download guard prevents collision bypass', downloadCount === 0 && alerts.length === 1);
T.autoDisambiguate = true;
check('auto-disambiguation clears final-name block', !T.outputBlockers(out).some(x => x.includes('duplicate final')));

console.log('\n[GFF feature ID integrity]');
T.resetState();
await T.loadFastaFiles([
  file('chrom.fasta', '>chr1\nAAAAAAAAAA'),
  file('plasmid.fasta', '>p1\nCCCCCCCCCC'),
]);
await T.loadGffFiles([
  file('chrom.gff3', 'chr1\ttool\tgene\t1\t2\t.\t+\t.\tID=gene1'),
  file('plasmid.gff3', 'p1\ttool\tgene\t1\t2\t.\t+\t.\tID=gene1'),
]);
const conflictOut = T.outputs[0];
for (const record of T.records) T.toggleMember(conflictOut.id, record.id, true);
check('same feature ID from different GFF sources blocks output', T.featureIdConflicts(conflictOut).has('gene1'));
check('feature-ID conflict appears in export blockers', T.outputBlockers(conflictOut).some(x => x.includes('feature ID')));
const beforeNamespace = T.buildGff(conflictOut, T.resolveExportNames());
T.namespaceFeatureIds = true;
check('opt-in namespacing clears a cross-file ID collision', T.featureIdConflicts(conflictOut).size === 0);
check('opt-in namespacing clears the cross-file conflict blocker', !T.outputBlockers(conflictOut).some(x => x.includes('feature ID')));
let namespacedGff = T.buildGff(conflictOut, T.resolveExportNames());
check('each GFF source receives a visible unique ID prefix',
  namespacedGff.includes('ID=chrom:gene1') && namespacedGff.includes('ID=plasmid:gene1'), namespacedGff);
T.namespaceFeatureIds = false;
check('turning namespacing off restores byte-identical output', T.buildGff(conflictOut, T.resolveExportNames()) === beforeNamespace);

T.resetState();
await T.loadFastaFiles([
  file('a.fasta', '>a\nAAAAAAAAAA'),
  file('b.fasta', '>b\nCCCCCCCCCC'),
]);
await T.loadGffFiles([
  file('a.gff3', [
    'a\ttool\tgene\t1\t9\t.\t+\t.\tID=gene1;Name=Shared name;Alias=shared;Target=external 1 9',
    'a\ttool\tmRNA\t1\t9\t.\t+\t.\tID=tx1;Parent=gene1',
    'a\ttool\tCDS\t1\t3\t.\t+\t0\tID=cds1;Parent=tx1',
    'a\ttool\tCDS\t7\t9\t.\t+\t0\tID=cds1;Parent=tx1',
    'a\ttool\tpolypeptide\t1\t9\t.\t+\t.\tID=pep1;Derives_from=tx1',
  ].join('\n')),
  file('b.gff3', [
    'b\ttool\tgene\t1\t9\t.\t+\t.\tID=gene1',
    'b\ttool\tmRNA\t1\t9\t.\t+\t.\tID=tx2;Parent=gene1',
  ].join('\n')),
]);
const graphOut = T.outputs[0];
for (const record of T.records) T.toggleMember(graphOut.id, record.id, true);
T.namespaceFeatureIds = true;
namespacedGff = T.buildGff(graphOut, T.resolveExportNames());
check('Parent references follow their same-source namespaced IDs',
  namespacedGff.includes('ID=a:tx1;Parent=a:gene1') && namespacedGff.includes('ID=b:tx2;Parent=b:gene1'), namespacedGff);
check('Derives_from follows its namespaced target',
  namespacedGff.includes('ID=a:pep1;Derives_from=a:tx1'), namespacedGff);
check('discontinuous rows retain one shared namespaced ID',
  (namespacedGff.match(/ID=a:cds1/g) || []).length === 2 && !T.featureIdConflicts(graphOut).has('a:cds1'), namespacedGff);
check('Name, Alias, and Target values remain unchanged',
  namespacedGff.includes('Name=Shared name;Alias=shared;Target=external 1 9'), namespacedGff);

T.resetState();
await T.loadFastaFiles([
  file('child.fasta', '>child\nAAAAAAAAAA'),
  file('parent.fasta', '>parent\nCCCCCCCCCC'),
  file('collision.fasta', '>collision\nGGGGGGGGGG'),
]);
await T.loadGffFiles([
  file('child.gff3', 'child\ttool\tmRNA\t1\t9\t.\t+\t.\tID=tx;Parent=remote_gene'),
  file('parent.gff3', 'parent\ttool\tgene\t1\t9\t.\t+\t.\tID=remote_gene'),
  file('collision.gff3', 'collision\ttool\tgene\t1\t9\t.\t+\t.\tID=tx'),
]);
const crossRefOut = T.outputs[0];
for (const record of T.records) T.toggleMember(crossRefOut.id, record.id, true);
T.namespaceFeatureIds = true;
namespacedGff = T.buildGff(crossRefOut, T.resolveExportNames());
check('unique cross-GFF Parent references use the target source prefix',
  namespacedGff.includes('ID=child:tx;Parent=parent:remote_gene'), namespacedGff);
check('resolved cross-GFF relationship has no safety blocker',
  T.relationshipReferenceIssues(crossRefOut).length === 0);

T.resetState();
await T.loadFastaFiles([
  file('child.fasta', '>child\nAAAAAAAAAA'),
  file('one.fasta', '>one\nCCCCCCCCCC'),
  file('two.fasta', '>two\nGGGGGGGGGG'),
]);
await T.loadGffFiles([
  file('child.gff3', [
    'child\ttool\tmRNA\t1\t9\t.\t+\t.\tID=tx;Parent=shared',
    'child\ttool\tmRNA\t1\t9\t.\t+\t.\tID=orphan_tx;Parent=missing',
  ].join('\n')),
  file('one.gff3', 'one\ttool\tgene\t1\t9\t.\t+\t.\tID=shared'),
  file('two.gff3', 'two\ttool\tgene\t1\t9\t.\t+\t.\tID=shared'),
]);
const unsafeRefOut = T.outputs[0];
for (const record of T.records) T.toggleMember(unsafeRefOut.id, record.id, true);
T.namespaceFeatureIds = true;
const unsafeIssues = T.relationshipReferenceIssues(unsafeRefOut);
check('ambiguous cross-GFF Parent targets block namespaced export',
  unsafeIssues.some(issue => issue.includes("Parent target ID 'shared' is ambiguous")));
check('missing Parent targets block namespaced export',
  unsafeIssues.some(issue => issue.includes("Parent target ID 'missing' does not exist")));
check('relationship failures are exposed through the export guard',
  T.outputBlockers(unsafeRefOut).some(blocker => blocker.includes('cannot be namespaced safely')));

T.resetState();
await T.loadFastaFiles([
  file('a.fasta', '>a\nAAAAAAAAAA'),
  file('b.fasta', '>b\nCCCCCCCCCC'),
]);
await T.loadGffFiles([
  file('a.gff3', [
    'a\ttool\tgene\t1\t4\t.\t+\t.\tID=gene1',
    'a\ttool\tmRNA\t6\t9\t.\t+\t.\tID=gene1',
  ].join('\n')),
  file('b.gff3', 'b\ttool\tgene\t1\t4\t.\t+\t.\tID=gene1'),
]);
const internalConflictOut = T.outputs[0];
for (const record of T.records) T.toggleMember(internalConflictOut.id, record.id, true);
T.namespaceFeatureIds = true;
check('namespacing does not hide a genuine within-source feature conflict',
  T.featureIdConflicts(internalConflictOut).has('a:gene1'));

T.resetState();
await T.loadFastaFiles([file('one.fasta', '>chr1\nAAAAAAAAAA')]);
await T.loadGffFiles([file('one.gff3', [
  '##species https://example.test/species',
  '##sequence-region chr1 2 8',
  'chr1\ttool\tCDS\t1\t2\t.\t+\t0\tID=cds1',
  'chr1\ttool\tCDS\t5\t6\t.\t+\t2\tID=cds1',
].join('\n'))]);
const discontinuousOut = T.outputs[0];
T.toggleMember(discontinuousOut.id, T.records[0].id, true);
check('legitimate discontinuous feature ID is silent', T.featureIdConflicts(discontinuousOut).size === 0 && T.outputBlockers(discontinuousOut).length === 0);
builtGff = T.buildGff(discontinuousOut, T.resolveExportNames());
T.namespaceFeatureIds = true;
check('toggle is a no-op when there is no cross-file collision',
  T.buildGff(discontinuousOut, T.resolveExportNames()) === builtGff);
check('supported global directive is preserved', builtGff.split('\n')[1] === '##species https://example.test/species');
check('both discontinuous rows are conserved', featureLines(builtGff).length === 2);
check('source sequence-region replacement is disclosed and output is full-length',
  T.outputWarnings(discontinuousOut).some(w => w.includes('will be regenerated as 1..10')) &&
  builtGff.includes('##sequence-region chr1 1 10'));

console.log('\n[orphans, bounds, prototypes]');
T.resetState();
await T.loadFastaFiles([file('x.fasta', '>__proto__\nAAAA')]);
await T.loadGffFiles([file('x.gff3', [
  '__proto__\ts\tgene\t1\t9\t.\t+\t.\tID=x',
  'ghost\ts\tgene\t1\t2\t.\t+\t.\tID=y',
].join('\n'))]);
const protoOut = T.outputs[0];
T.toggleMember(protoOut.id, T.records[0].id, true);
check('prototype-key seqid does not crash maps', T.featureCount(T.records[0]) === 1);
check('orphan seqid is reported', T.orphanSeqids().includes('ghost'));
check('out-of-bounds feature warns rather than blocks',
  T.outputWarnings(protoOut).some(x => x.includes('exceeds')) && !T.outputBlockers(protoOut).some(x => x.includes('exceeds')));

console.log('\n[circular topology and export preservation]');
const circularPassStart = pass;
const circularFailStart = fail;
const landmark = (attrs = 'Is_circular=true', start = 1, end = 60) =>
  `p\ts\tregion\t${start}\t${end}\t.\t+\t.\tID=landmark;${attrs}`;
const wrap = (start = 55, end = 65, strand = '+') =>
  `p\ts\tCDS\t${start}\t${end}\t.\t${strand}\t0\tID=wrap`;
// Each scenario exercises the actual individual and ZIP download guards. Keep
// the real ZIP writer here; the older ZIP-name test below replaces it with a stub.
const circularCases = [
  { name: 'linear overrun', rows: [wrap()], warns: true },
  { name: 'explicit linear landmark', rows: [landmark('Is_circular=false'), wrap()], warns: true },
  { name: 'unmarked landmark', rows: [landmark('Name=p'), wrap()], warns: true },
  { name: 'circular wrap', rows: [landmark(), wrap()] },
  { name: 'reverse-strand wrap', rows: [landmark(), wrap(55, 65, '-')] },
  { name: 'first virtual endpoint', rows: [landmark(), wrap(60, 61)] },
  { name: 'last virtual endpoint', rows: [landmark(), wrap(60, 120)] },
  { name: 'end beyond next copy', rows: [landmark(), wrap(55, 121)], warns: true },
  { name: 'start beyond landmark', rows: [landmark(), wrap(61, 65)], warns: true },
  { name: 'reversed endpoints', rows: [landmark(), wrap(55, 5)], blocked: true },
  { name: 'zero start', rows: [landmark(), wrap(0, 65)], blocked: true },
  { name: 'negative start', rows: [landmark(), wrap(-1, 65)], blocked: true },
  { name: 'short landmark', rows: [landmark('Is_circular=true', 1, 59), wrap()], warns: true },
  { name: 'offset landmark', rows: [landmark('Is_circular=true', 2, 60), wrap()], warns: true },
  { name: 'circular child', rows: [landmark('Is_circular=true;Parent=parent'), wrap()], warns: true },
  { name: 'noncanonical circular value', rows: [landmark('Is_circular=True'), wrap()], warns: true },
  { name: 'duplicate contradictory attributes', rows: [landmark('Is_circular=false;Is_circular=true'), wrap()], warns: true },
  { name: 'conflicting landmarks', rows: [landmark(), landmark('Is_circular=false').replace('ID=landmark;', 'ID=other;'), wrap()], warns: true },
  { name: 'conflicting matched source', rows: [landmark(), wrap()], extra: landmark('Is_circular=false').replace('ID=landmark;', 'ID=other;'), warns: true },
  { name: 'topology from another matched source', rows: [wrap()], extra: landmark() },
  { name: 'linear in-bounds', rows: [wrap(1, 60)] },
  { name: 'circular split rows', rows: [landmark(), wrap(55, 60), wrap(1, 5)] },
  { name: 'mismatched sequence-region stays visible', rows: ['##sequence-region p 1 59', landmark(), wrap()], regionWarn: true },
];
for (const scenario of circularCases) {
  T.resetState();
  await T.loadFastaFiles([file('p.fa', '>p original description\n' + 'ACGT'.repeat(15))]);
  await T.loadGffFiles([file('p.gff3', scenario.rows.join('\n'))]);
  if (scenario.extra) await T.loadGffFiles([file('extra.gff3', scenario.extra)]);
  const record = T.records[0];
  record.exportName = 'renamed';
  const output = T.outputs[0];
  T.toggleMember(output.id, record.id, true);
  const warnings = T.outputWarnings(output);
  check(`${scenario.name}: bounds warning`, warnings.some(w => w.includes('exceeds')) === !!scenario.warns, warnings);
  check(`${scenario.name}: region warning`, warnings.some(w => w.includes('will be regenerated')) === !!scenario.regionWarn, warnings);
  const downloads = [];
  T.setDownloadCapture((blob, name) => downloads.push({ blob, name }));
  alerts = []; confirms = [];
  T.downloadOutput(output.id, 'fasta');
  T.downloadOutput(output.id, 'gff');
  T.downloadAllZip();
  check(`${scenario.name}: all export guards agree`, scenario.blocked
    ? downloads.length === 0 && alerts.length === 3 && confirms.length === 0
    : downloads.length === 3 && alerts.length === 0 && confirms.length === (scenario.warns || scenario.regionWarn ? 3 : 0));
  if (scenario.blocked) continue;
  const expectedFasta = '>renamed original description\n' + 'ACGT'.repeat(15) + '\n';
  const expectedRows = [...scenario.rows, ...(scenario.extra ? [scenario.extra] : [])]
    .filter(row => !row.startsWith('#')).map(row => row.replace(/^p\t/, 'renamed\t'));
  const expectedGff = '##gff-version 3\n##sequence-region renamed 1 60\n' + expectedRows.join('\n') + '\n';
  check(`${scenario.name}: individual exports preserve physical sequence and exact feature columns`,
    await downloads[0].blob.text() === expectedFasta && await downloads[1].blob.text() === expectedGff);
  const zip = Buffer.from(await downloads[2].blob.arrayBuffer());
  const entries = new Map();
  let offset = 0;
  while (zip.readUInt32LE(offset) === 0x04034b50) {
    const size = zip.readUInt32LE(offset + 18);
    const nameSize = zip.readUInt16LE(offset + 26);
    const extraSize = zip.readUInt16LE(offset + 28);
    const name = zip.subarray(offset + 30, offset + 30 + nameSize).toString();
    const dataStart = offset + 30 + nameSize + extraSize;
    entries.set(name, zip.subarray(dataStart, dataStart + size).toString());
    offset = dataStart + size;
  }
  check(`${scenario.name}: real ZIP preserves the same FASTA and GFF`,
    entries.size === 2 && entries.get(output.name + '.fasta') === expectedFasta && entries.get(output.name + '.gff') === expectedGff);
}

T.resetState();
await T.loadFastaFiles([file('one.fa', '>p\n' + 'A'.repeat(60)), file('two.fa', '>p\n' + 'C'.repeat(30))]);
await T.loadGffFiles([file('metadata.gff3', landmark()), file('features.gff3', wrap())]);
const matchedOut = T.outputs[0];
for (const record of T.records) T.toggleMember(matchedOut.id, record.id, true);
T.autoDisambiguate = true;
const matches = T.ambiguousGffMatches();
T.assignGffMatch(matches.find(m => m.source.name === 'metadata.gff3').key, T.records[0].id);
const featureMatch = matches.find(m => m.source.name === 'features.gff3');
T.assignGffMatch(featureMatch.key, T.records[1].id);
check('circular metadata cannot leak to another FASTA with the same seqid', T.outputWarnings(matchedOut).some(w => w.includes('exceeds p length 30')));
T.assignGffMatch(featureMatch.key, T.records[0].id);
check('reassignment uses the chosen record topology without stale state', T.outputWarnings(matchedOut).length === 0);
const matchedNames = T.resolveExportNames();
check('auto-disambiguated circular features follow the assigned record',
  featureLines(T.buildGff(matchedOut, matchedNames)).every(row => row.startsWith(matchedNames[T.records[0].id] + '\t')));
console.log(`Circular regressions: ${circularCases.length} coordinate/topology scenarios + 1 assignment scenario; ${pass - circularPassStart} passed, ${fail - circularFailStart} failed`);

console.log('\n[ZIP + scale]');
T.resetState();
await T.loadFastaFiles([file('x.fasta', '>x\nAAAA')]);
for (const name of ['foo', 'foo', 'foo.2', 'constructor']) {
  T.addOutput();
  const current = T.outputs.at(-1);
  current.name = name;
  T.toggleMember(current.id, T.records[0].id, true);
}
// addOutput from the first FASTA load made an unused empty output; it is intentionally ignored.
let zipNames = [];
T.setZipCapture(files => { zipNames = files.map(item => item.name); return new Blob([]); });
T.downloadAllZip();
check('ZIP entry names are unique for foo/foo/foo.2', new Set(zipNames).size === zipNames.length, zipNames);
check('prototype-like output name remains stable', zipNames.includes('constructor.fasta'), zipNames);
check('ZIP safety ceiling is named and finite', Number.isFinite(T.maxZipBytes) && T.maxZipBytes > 0);
const many = Array.from({ length: 150000 }, (_, i) => ({ length: i === 149999 ? 7 : 1 }));
check('large record count max does not use spread', T.maxSequenceLength(many) === 7);

console.log('\n[original fixture smoke]');
T.resetState();
const chrom = fs.readFileSync(new NativeURL('chromosome.fasta', import.meta.url), 'utf8');
const plas = fs.readFileSync(new NativeURL('plasmids.fasta', import.meta.url), 'utf8');
const gff = fs.readFileSync(new NativeURL('anno.gff3', import.meta.url), 'utf8');
await T.loadFastaFiles([file('chromosome.fasta', chrom), file('plasmids.fasta', plas)]);
await T.loadGffFiles([file('anno.gff3', gff)]);
const smokeOut = T.outputs[0];
for (const record of T.records) T.toggleMember(smokeOut.id, record.id, true);
names = T.resolveExportNames();
const fastaOut = T.buildFasta(smokeOut, names);
builtGff = T.buildGff(smokeOut, names);
check('fixture FASTA keeps all three records', headers(fastaOut) === 3);
check('fixture GFF conserves three matched features', featureLines(builtGff).length === 3);
check('fixture orphan is omitted', !builtGff.includes('ghost_seq'));
const blob = T.makeZip([{ name: 'a.txt', data: new TextEncoder().encode('hello') }]);
const buf = Buffer.from(await blob.arrayBuffer());
check('ZIP writer emits local and EOCD signatures',
  buf.subarray(0, 4).equals(Buffer.from([0x50,0x4b,0x03,0x04])) &&
  buf.includes(Buffer.from([0x50,0x4b,0x05,0x06])));
check('crc32 known vector remains correct', T.crc32(new TextEncoder().encode('123456789')) === 0xCBF43926);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
