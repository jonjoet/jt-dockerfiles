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
  'tableHead','tableBody','outputsSummary','exportInfo','exportBtn']) store[id] = fakeEl();

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
  downloadOutput, downloadAllZip,
  get records(){ return records; },
  get outputs(){ return outputs; },
  get gffSources(){ return gffSources; },
  get maxZipBytes(){ return MAX_ZIP_BYTES; },
  set autoDisambiguate(v){ autoDisambiguate = v; },
  resetState(){
    loadGeneration++;
    records = []; outputs = []; gffSources = []; gffAssignments = new Map();
    fastaFileNames = []; recordSeq = 0; outputSeq = 0; fastaSourceSeq = 0; gffSourceSeq = 0;
    sortCol = 'length'; sortDir = -1; autoDisambiguate = false;
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

T.resetState();
await T.loadFastaFiles([file('one.fasta', '>chr1\nAAAAAAAAAA')]);
await T.loadGffFiles([file('one.gff3', [
  '##species https://example.test/species',
  'chr1\ttool\tCDS\t1\t2\t.\t+\t0\tID=cds1',
  'chr1\ttool\tCDS\t5\t6\t.\t+\t2\tID=cds1',
].join('\n'))]);
const discontinuousOut = T.outputs[0];
T.toggleMember(discontinuousOut.id, T.records[0].id, true);
check('legitimate discontinuous feature ID is silent', T.featureIdConflicts(discontinuousOut).size === 0 && T.outputBlockers(discontinuousOut).length === 0);
builtGff = T.buildGff(discontinuousOut, T.resolveExportNames());
check('supported global directive is preserved', builtGff.split('\n')[1] === '##species https://example.test/species');
check('both discontinuous rows are conserved', featureLines(builtGff).length === 2);

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
