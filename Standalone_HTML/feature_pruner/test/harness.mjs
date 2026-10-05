import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

// Exercise the real embedded script, following the adjacent standalone tools.
// No browser packages, network access, or build step are needed for this harness.
const html = fs.readFileSync(new URL('../feature_pruner.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
const documentListeners = {};
function element(id) {
  if (elements.has(id)) return elements.get(id);
  let markup = '';
  const el = {
    value: '', checked: false, disabled: false, indeterminate: false,
    textContent: '', dataset: {}, listeners: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    scrollIntoView() {}, click() {}, remove() {}, setAttribute() {},
    get innerHTML() { return markup; },
    set innerHTML(value) {
      markup = value;
      if (id === 'mapSeq') this.value = value.match(/value="([^"]*)"/)?.[1] || '';
    },
  };
  elements.set(id, el);
  return el;
}
const context = vm.createContext({
  document: {
    getElementById: element,
    addEventListener: (name, fn) => { documentListeners[name] = fn; },
    createElement: () => element('downloadAnchor'),
    body: { append() {}, classList: { add() {}, remove() {} } },
  },
  window: { addEventListener() {} },
  confirm: () => true,
  Blob, TextDecoder, URL, setTimeout,
});
const T = vm.runInContext(script + `\n;({
  parseGff, parseFasta, exportText, integrity, fastaNotes, esc,
  init, change, loadFiles, matchingFeatures, renderDetails,
  get model() { return model; },
  get history() { return history; },
  inspect(uid) { selected = uid; renderDetails(); },
});`, context);

let passed = 0;
async function check(name, fn) {
  await fn();
  passed++;
  console.log('  ✓ ' + name);
}
const row = (id, overrides = {}) => {
  const r = { seq: 'p', source: 'Benchling', type: 'CDS', start: 10, end: 99,
    strand: '+', phase: '0', attrs: `ID=${id};Name=${id}`, ...overrides };
  return [r.seq, r.source, r.type, r.start, r.end, '.', r.strand, r.phase, r.attrs].join('\t');
};
const gff = (...rows) => '##gff-version 3\n' + rows.join('\n') + '\n';
const file = (name, text) => ({ name, size: Buffer.byteLength(text), arrayBuffer: async () => Buffer.from(text) });

await check('all annotations are initially retained; distinct IDs and names group together', () => {
  const m = T.parseGff(gff(row('a'), row('b', { source: 'Imported', attrs: 'ID=b;Name=another%20name' })));
  assert.equal(m.features.length, 2);
  assert.equal(m.groups.length, 1);
  assert.ok(m.features.every(f => f.keep));
  assert.equal(m.features[1].name, 'another name');
});
await check('different sequence, type, strand, or coordinates remain separate', () => {
  const m = T.parseGff(gff(row('a'), row('b', { seq: 'q' }), row('c', { type: 'gene' }),
    row('d', { strand: '-' }), row('e', { start: 11 })));
  assert.equal(m.groups.length, 5);
});
await check('CDS phase differences group as candidates but remain visible and unchanged', () => {
  const input = gff(row('a'), row('b', { phase: '1' }));
  const m = T.parseGff(input);
  assert.equal(m.groups.length, 1);
  assert.equal(m.features[1].rows[0].phase, '1');
  assert.equal(T.exportText(m), input);
});
await check('multipart IDs are indivisible; complete segment sets determine matches', () => {
  const m = T.parseGff(gff(row('a'), row('a', { start: 200, end: 299 }),
    row('b', { start: 200, end: 299 }), row('b'), row('c', { start: 10, end: 299 })));
  assert.equal(m.features.length, 3);
  assert.equal(m.groups.length, 2);
  assert.equal(m.features[0].group.features.length, 2);
  m.features[0].keep = false;
  assert.ok(!T.exportText(m).includes('ID=a;'));
  assert.equal((T.exportText(m).match(/ID=b;/g) || []).length, 2);
});
await check('retained lines, BOM, mixed line endings, directives, and embedded FASTA round-trip', () => {
  const input = '\uFEFF##gff-version 3\r\n# A comment\r' + row('a') + '\n###\r\n' +
    row('b', { attrs: 'ID=b;Note=a%3Bb%2Cc;Dbxref=DB:1,DB:2' }) + '\r\n##FASTA\n>p\r\n' + 'A'.repeat(120);
  const m = T.parseGff(input);
  assert.equal(T.exportText(m), input);
  m.features[0].keep = false;
  assert.equal(T.exportText(m), input.replace(row('a') + '\n', ''));
  assert.equal(m.lengths.get('p'), 120);
});
await check('last line without a newline is preserved or removed cleanly', () => {
  const input = gff(row('a')) + row('b');
  const m = T.parseGff(input);
  assert.equal(T.exportText(m), input);
  m.features[1].keep = false;
  assert.equal(T.exportText(m), gff(row('a')));
});
await check('features without IDs can be independently reviewed', () => {
  const m = T.parseGff(gff(row('', { attrs: 'Name=x' }), row('', { attrs: '.' })));
  assert.equal(m.features.length, 2);
  m.features[0].keep = false;
  assert.ok(!T.exportText(m).includes('Name=x'));
});
await check('parent and derivation checks distinguish removed from already missing targets', () => {
  const m = T.parseGff(gff(row('g', { type: 'gene' }), row('c', { attrs: 'ID=c;Parent=g;Derives_from=unknown' })));
  m.features[0].keep = false;
  const p = T.integrity(m);
  assert.equal(p.removed.length, 1);
  assert.equal(p.removed[0].id, 'g');
  assert.equal(p.missing.length, 1);
  assert.equal(p.missing[0].id, 'unknown');
});
await check('escaped commas remain part of IDs; literal commas separate references', () => {
  const m = T.parseGff(gff(row('', { type: 'gene', attrs: 'ID=g%2C1' }),
    row('g2', { type: 'gene' }), row('c', { attrs: 'ID=c;Parent=g%2C1,g2' })));
  assert.equal(T.integrity(m).missing.length, 0);
  assert.equal(m.features[2].refs.length, 2);
});
await check('conflicting reuse of a feature ID is rejected', () => {
  assert.throws(() => T.parseGff(gff(row('same'), row('same', { seq: 'q' }))), /conflicting/);
  assert.throws(() => T.parseGff(gff(row('same'), row('same', { type: 'gene' }))), /conflicting/);
});
await check('malformed GFF3 fails with a line-numbered error', () => {
  assert.throws(() => T.parseGff('##gff-version 3\na\tb'), /line 2/);
  assert.throws(() => T.parseGff(gff(row('a', { start: 100, end: 99 }))), /coordinates/);
  assert.throws(() => T.parseGff(gff(row('a', { phase: '4' }))), /phase/);
  assert.throws(() => T.parseGff(gff(row('a', { attrs: 'gene_id "a";' }))), /Malformed attribute/);
  assert.throws(() => T.parseGff(gff(row('a', { attrs: 'ID=a;ID=b' }))), /Repeated attribute/);
});
await check('FASTA supports multiline records and reports ambiguous/invalid input', () => {
  const lengths = T.parseFasta('\uFEFF>p description\rAC GT\rNN\r>q\rAAA');
  assert.equal(lengths.get('p'), 6);
  assert.equal(lengths.get('q'), 3);
  assert.throws(() => T.parseFasta('>p\nA\n>p\nC'), /Repeated FASTA/);
  assert.throws(() => T.parseFasta('>p\n'), /Empty FASTA/);
  assert.throws(() => T.parseFasta('>p\n123'), /Unrecognized/);
});
await check('FASTA mismatch and origin-spanning positions warn without modifying GFF3', () => {
  const input = gff(row('a', { end: 150 }), row('b', { seq: 'unknown' }));
  const m = T.parseGff(input);
  m.lengths = T.parseFasta('>p\n' + 'A'.repeat(100));
  const notes = T.fastaNotes(m).join(' ');
  assert.ok(notes.includes('unknown'));
  assert.ok(notes.includes('origin-spanning'));
  assert.equal(T.exportText(m), input);
});
await check('rendered feature names and attributes cannot inject HTML', () => {
  const name = '<img src=x onerror=alert(1)>';
  const m = T.parseGff(gff(row('a', { attrs: 'ID=a;Name=' + encodeURIComponent(name) })));
  T.init(m);
  T.inspect(0);
  assert.ok(element('rows').innerHTML.includes('&lt;img'));
  assert.ok(!element('rows').innerHTML.includes('<img'));
  assert.ok(!element('inspector').innerHTML.includes('<img'));
});
await check('filtering the table never removes hidden annotations from export', () => {
  const input = gff(row('a'), row('b'), row('unique', { start: 101, end: 200 }));
  T.init(T.parseGff(input));
  element('duplicatesOnly').checked = true;
  assert.equal(T.matchingFeatures().length, 1);
  assert.equal(T.exportText(T.model), input);
});
await check('visible-only bulk selection and undo restore the original retention state', () => {
  T.init(T.parseGff(gff(row('a'), row('b'), row('unique', { start: 101, end: 200 }))));
  element('search').value = 'unique';
  element('search').listeners.input();
  element('visibleKeep').listeners.change({ target: { checked: false } });
  assert.equal(T.model.features.filter(f => f.keep).length, 2);
  assert.equal(T.model.features[2].keep, false);
  element('undo').onclick();
  assert.ok(T.model.features.every(f => f.keep));
});
await check('restoring required features follows multi-level relationships', () => {
  T.init(T.parseGff(gff(row('g', { type: 'gene' }), row('t', { type: 'mRNA', attrs: 'ID=t;Parent=g' }),
    row('c', { attrs: 'ID=c;Parent=t' }))));
  T.change(() => { T.model.features[0].keep = false; T.model.features[1].keep = false; });
  assert.equal(element('download').disabled, true);
  element('restoreRefs').onclick();
  assert.equal(element('download').disabled, false);
  assert.ok(T.model.features.every(f => f.keep));
});
await check('UTF-8 file loading preserves a BOM and supports adding FASTA afterward', async () => {
  const input = '\uFEFF' + gff(row('a'));
  await T.loadFiles([file('input.gff3', input)]);
  assert.equal(T.exportText(T.model), input);
  await T.loadFiles([file('input.fa', '>p\n' + 'A'.repeat(100))]);
  assert.equal(T.model.lengths.get('p'), 100);
  assert.equal(T.model.name, 'input.gff3');
});
await check('an older asynchronous upload cannot replace a newer review', async () => {
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  const slow = T.loadFiles([{ name: 'slow.gff3', size: 100, arrayBuffer: () => pending }]);
  await T.loadFiles([file('new.gff3', gff(row('new')))]);
  release(Buffer.from(gff(row('old'))));
  await slow;
  assert.equal(T.model.name, 'new.gff3');
  assert.equal(T.model.features[0].id, 'new');
});
await check('failed parsing leaves the current review intact', async () => {
  const current = T.model;
  await T.loadFiles([file('bad.gff3', 'not a GFF3')]);
  assert.equal(T.model, current);
  assert.ok(element('message').textContent.includes('9 tab-separated'));
});
await check('all features can be removed without losing comments or sequence', () => {
  const m = T.parseGff(gff(row('a')) + '##FASTA\n>p\nAAAA\n');
  m.features[0].keep = false;
  assert.equal(T.exportText(m), '##gff-version 3\n##FASTA\n>p\nAAAA\n');
});
await check('single-file app declares no external script, style, or network dependencies', () => {
  assert.ok(!/<script[^>]+src=|<link[^>]+href=/i.test(html));
  assert.ok(html.includes("connect-src 'none'"));
  assert.ok(!/\bfetch\(|XMLHttpRequest|WebSocket\(/.test(script));
});

console.log(`\n${passed} checks passed.`);
