import fs from 'fs';

const html = fs.readFileSync(new URL('../assembly_filter_with_rename.html', import.meta.url), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];

const store = {};
function fakeEl() {
  return {
    listeners: {},
    classList: { add(){}, remove(){}, toggle(){} },
    addEventListener(type, fn){ this.listeners[type] = fn; },
    style: {},
    value: '',
    innerHTML: '',
    textContent: '',
    disabled: false,
    dataset: {},
    querySelector(){ return null; },
    focus(){},
    select(){},
  };
}

for (const id of ['fastaInput','gffInput','refInput','fastaBox','gffBox','refBox',
  'fastaFileName','gffFileName','refFileName','diagnosticsBanner','workspace',
  'emptyState','statsBar','searchBox','minLenInput','resetRenamesBtn','exportInfo',
  'exportBtn','tableHead','tableBody','bulkRenamePanel','renamePrefix','renameSuffix',
  'renameFind','renameReplace']) store[id] = fakeEl();

globalThis.document = {
  getElementById: id => store[id] || (store[id] = fakeEl()),
  createElement: () => ({ click(){}, style: {} }),
  body: { appendChild(){}, removeChild(){} },
};
globalThis.alert = () => {};
globalThis.confirm = () => true;
globalThis.URL = { createObjectURL: () => 'blob:', revokeObjectURL(){} };

const T = eval(script + `
;({
  parseFasta, parseFastaDetailed, parseGff, maxSequenceLength, escapeHtml,
  exportBlockers, exportWarnings, buildFastaOutput, buildGffOutput, renderDiagnostics,
  setAssembly(text) {
    const parsed = parseFastaDetailed(text, 'q');
    sequences = parsed.records;
    fastaDiagnostics = { errors: parsed.errors, warnings: parsed.warnings };
    maxLen = maxSequenceLength(sequences);
    return parsed;
  },
  setGff(text) {
    const parsed = parseGff(text);
    gffItems = parsed.items;
    gffLines = parsed.features;
    gffMap = parsed.map;
    gffSeqids = parsed.seqids;
    gffEmbeddedNames = parsed.embeddedNames;
    gffDiagnostics = { errors: parsed.errors, warnings: parsed.warnings };
    gffFileName = 'test.gff3';
    return parsed;
  },
  clearGff() {
    gffItems = []; gffLines = []; gffMap = new Map(); gffSeqids = new Set();
    gffEmbeddedNames = new Set(); gffDiagnostics = { errors: [], warnings: [] };
    gffFileName = '';
  },
  get records(){ return sequences; },
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

console.log('\n[FASTA parsing]');
let parsed = T.parseFastaDetailed('\uFEFF>first\rAC GT\r>second\rNN', 'q');
check('BOM and CR-only input preserve both records', parsed.records.length === 2, parsed.records.map(r => r.name));
check('internal sequence whitespace is normalized', parsed.records[0].sequence === 'ACGT', parsed.records[0].sequence);
check('whitespace normalization is reported with line number', parsed.warnings.some(w => w.includes('line 2')));
parsed = T.parseFastaDetailed('>\nACGT');
check('empty FASTA identifier is a hard parse error', parsed.errors.some(e => e.includes('identifier is empty')));
check('HTML escaping covers markup and quotes', T.escapeHtml(`<x a="'">`).includes('&lt;x'));
T.setAssembly('>\nACGT');
T.renderDiagnostics();
check('diagnostic banner is visibly displayed for hard errors', store.diagnosticsBanner.style.display === 'block' && store.exportBtn.disabled);

console.log('\n[selection identity + renaming]');
T.clearGff();
T.setAssembly('>dup\nAAAA\n>dup\nCCCC');
T.records[0].selected = false;
let selected = T.records.filter(r => r.selected);
let fasta = T.buildFastaOutput(selected);
check('export record count equals checked record count', (fasta.match(/^>/gm) || []).length === selected.length);
check('deselected duplicate sequence is absent', !fasta.includes('AAAA') && fasta.includes('CCCC'), fasta);
T.records[0].selected = true;
T.records[0].renamed = 'same';
T.records[1].renamed = 'same';
check('duplicate final identifiers block export', T.exportBlockers().some(e => e.includes('duplicate final')));

console.log('\n[GFF parsing + export]');
T.setAssembly('>a\nAAAA\n>b\nCCCC');
let gff = T.setGff([
  '##gff-version 3',
  '##species https://example.test/species',
  '##sequence-region a 2 4',
  '##sequence-region b 1 4',
  'a\tsrc\tgene\t1\t4\t.\t+\t.\tID=g1',
  '###',
  'b\tsrc\tgene\t1\t4\t.\t+\t.\tID=g2',
  '##FASTA',
  '>a',
  'AAAA',
].join('\n'));
check('embedded FASTA is parsed separately from features', gff.features.length === 2 && gff.embeddedNames.has('a'));
T.records[0].renamed = 'renamed_a';
T.records[1].selected = false;
let gffOut = T.buildGffOutput(T.records.filter(r => r.selected));
check('gff-version is output line one', gffOut.startsWith('##gff-version 3\n'));
check('selected sequence-region coordinates are preserved and seqid renamed', gffOut.includes('##sequence-region renamed_a 2 4'));
check('deselected sequence-region and features are absent', !gffOut.includes('##sequence-region b ') && !gffOut.includes('\nb\t'));
check('embedded FASTA directive/content is omitted', !gffOut.includes('##FASTA') && !gffOut.includes('>a'));
check('global directive is preserved', gffOut.includes('##species https://example.test/species'));

gff = T.parseGff('a\ttoo\tfew');
check('malformed GFF row reports a line error', gff.errors.some(e => e.includes('exactly 9')));
gff = T.parseGff('a\ts\tgene\t4\t2\t.\t+\t.\tID=x');
check('reversed coordinates report a line error', gff.errors.some(e => e.includes('coordinates')));
gff = T.parseGff('a\ts\tgene\t1\t2\t.\t+\t.\tgene_id "x"; transcript_id "t"');
check('GTF attribute syntax is rejected by content', gff.errors.some(e => e.includes('GTF syntax')));
gff = T.parseGff('a\ts\tgene\t1\t2\t.\t+\t.\tgene_id "A=B"; transcript_id "t"');
check('inconclusive GTF-like syntax containing equals warns', gff.errors.length === 0 && gff.warnings.some(w => w.includes('may use GTF')));
gff = T.parseGff('a\ts\tgene\t1\t2\t.\t+\t.\tNote="quoted text";ID=x');
check('ordinary GFF3 attribute containing quotes is accepted', gff.errors.length === 0, gff.errors);
gff = T.parseGff('a\ts\tgene\t1\t2\t.\t+\t.\tID=x;Note=has "quoted" text');
check('quoted phrase inside GFF3 free text is silent', gff.errors.length === 0 && gff.warnings.length === 0, gff.warnings);
gff = T.parseGff('a\ts\tCDS\t1\t2\t.\t+\t9\tID=x');
check('invalid GFF3 phase is rejected', gff.errors.some(e => e.includes('phase')));

console.log('\n[ambiguity + warnings]');
T.setAssembly('>dup\nAAAA\n>dup\nCCCC');
T.setGff('dup\ts\tgene\t1\t4\t.\t+\t.\tID=x');
check('duplicate original IDs with matched GFF block export', T.exportBlockers().some(e => e.includes('cannot be assigned')));
T.setGff('##sequence-region dup 1 4');
T.records[0].renamed = 'dup.one';
T.records[1].renamed = 'dup.two';
check('duplicate originals without matched features may export after unique rename',
  !T.exportBlockers().some(e => e.includes('cannot be assigned')));
T.setAssembly('>kept\nAAAA\n>dropped\nCCCC');
T.records[1].selected = false;
T.setGff('dropped\ts\tgene\t1\t4\t.\t+\t.\tID=x');
check('deselected but known GFF seqid does not warn as orphan', !T.exportWarnings().some(w => w.includes('absent from')));
T.setGff('ghost\ts\tgene\t1\t4\t.\t+\t.\tID=x');
check('truly absent GFF seqid warns', T.exportWarnings().some(w => w.includes('ghost')));
T.setGff('kept\ts\tgene\t1\t9\t.\t+\t.\tID=x');
check('feature beyond FASTA length warns rather than blocks',
  T.exportWarnings().some(w => w.includes('exceeds')) && !T.exportBlockers().some(w => w.includes('exceeds')));
T.setGff('##sequence-region kept 2 9\nkept\ts\tgene\t1\t4\t.\t+\t.\tID=x');
check('sequence-region beyond FASTA length warns and preserves declared range',
  T.exportWarnings().some(w => w.includes('sequence-region end')) &&
  T.buildGffOutput(T.records.filter(r => r.selected)).includes('##sequence-region kept 2 9'));
T.setGff('kept\ts\tgene\t1\t4\t.\t+\t.\tID=x');
check('missing sequence-region falls back to full FASTA bounds',
  T.buildGffOutput(T.records.filter(r => r.selected)).includes('##sequence-region kept 1 4'));

console.log('\n[scale + async race]');
const many = Array.from({ length: 150000 }, (_, i) => ({ length: i === 149999 ? 9 : 1 }));
check('maximum length does not use spread argument list', T.maxSequenceLength(many) === 9);
let releaseSlow;
const slow = new Promise(resolve => { releaseSlow = resolve; });
const slowLoad = store.fastaInput.listeners.change({ target: { files: [{ name: 'slow.fa', text: () => slow }] } });
const fastLoad = store.fastaInput.listeners.change({ target: { files: [{ name: 'fast.fa', text: async () => '>fast\nAAAA' }] } });
await fastLoad;
releaseSlow('>slow\nCCCC');
await slowLoad;
check('stale async FASTA read cannot replace newer file', T.records.length === 1 && T.records[0].name === 'fast', T.records.map(r => r.name));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
