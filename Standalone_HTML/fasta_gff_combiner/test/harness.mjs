import fs from 'fs';

const html = fs.readFileSync('fasta_gff_combiner.html', 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];

// ── minimal DOM stub ──
const store = {};
function fakeEl() {
  return new Proxy({
    _value: '', classList: { add(){}, remove(){} },
    addEventListener(){}, style: {}, innerHTML: '', textContent: '',
    querySelector(){ return null; }, focus(){}, select(){}, dataset:{},
    get value(){ return this._value; }, set value(v){ this._value = v; },
  }, {});
}
for (const id of ['fastaInput','gffInput','fastaBox','gffBox','fileChips','workspace',
  'emptyState','warnBanner','statsBar','searchBox','autoDisambig','tableHead',
  'tableBody','outputsSummary','exportInfo','exportBtn']) store[id] = fakeEl();

globalThis.document = {
  getElementById: id => store[id] || (store[id]=fakeEl()),
  createElement: () => ({ click(){}, style:{} }),
  body: { appendChild(){}, removeChild(){} },
};
globalThis.alert = m => console.log('ALERT:', m);
globalThis.confirm = () => true;
globalThis.URL = { createObjectURL: () => 'blob:', revokeObjectURL(){} };

// expose all top-level fns/vars: eval in module scope then grab via regex-free approach
const exported = eval(script + '\n;({parseFasta,parseGff,resolveExportNames,collisionInfo,buildFasta,buildGff,crc32,makeZip,addOutput,toggleMember,get records(){return records},get outputs(){return outputs},set autoDisambiguate(v){autoDisambiguate=v}, get autoDisambiguate(){return autoDisambiguate}, rematchGff, rebuild, gffPush(t){const f=parseGff(t);for(const x of f){const s=x.cols[0];(gffBySeqid[s]=gffBySeqid[s]||[]).push(x);} }, orphanSeqids });');

const T = exported;
let pass=0, fail=0;
function check(name, cond, extra='') { if(cond){pass++;console.log('  ✓',name);} else {fail++;console.log('  ✗ FAIL',name,extra);} }

// ── Load fixtures the way the app does ──
const chrom = fs.readFileSync('test/chromosome.fasta','utf8');
const plas  = fs.readFileSync('test/plasmids.fasta','utf8');
const coll  = fs.readFileSync('test/contig_collide.fasta','utf8');
const gff   = fs.readFileSync('test/anno.gff3','utf8');

const recs = [];
recs.push(...T.parseFasta(chrom,'chromosome.fasta'));
recs.push(...T.parseFasta(plas,'plasmids.fasta'));
recs.push(...T.parseFasta(coll,'contig_collide.fasta'));
T.records.push(...recs);
T.gffPush(gff);

console.log('\n[parse]');
check('4 records parsed', T.records.length===4, T.records.length);
const chr1 = T.records.find(r=>r.name==='chr1' && r.sourceFile==='chromosome.fasta');
check('chr1 length 120', chr1.length===120, chr1.length);
check('chr1 desc preserved', chr1.desc==='main chromosome');
const pA = T.records.find(r=>r.name==='pA');
check('pA length 60', pA.length===60, pA.length);

console.log('\n[gff match / orphans]');
check('orphan seqid detected', T.orphanSeqids().includes('ghost_seq'));
// (chr1 features verified in build-GFF section below)

console.log('\n[outputs + collision]');
T.addOutput(); // genome_1
const o1 = T.outputs[0];
// put chr1(chromosome) + both plasmids in o1
T.toggleMember(o1.id, chr1.id, true);
T.toggleMember(o1.id, pA.id, true);
T.toggleMember(o1.id, T.records.find(r=>r.name==='pB').id, true);
let nm = T.resolveExportNames();
let coll1 = T.collisionInfo(nm);
check('o1 no collision (distinct names)', coll1[o1.id].size===0);

// second output: chr1 from BOTH source files -> collision
T.addOutput();
const o2 = T.outputs[1];
const chr1b = T.records.find(r=>r.name==='chr1' && r.sourceFile==='contig_collide.fasta');
T.toggleMember(o2.id, chr1.id, true);
T.toggleMember(o2.id, chr1b.id, true);
nm = T.resolveExportNames();
coll1 = T.collisionInfo(nm);
check('o2 collision detected (2 chr1)', coll1[o2.id].size===2, coll1[o2.id].size);

// enable auto-disambiguate
T.autoDisambiguate = true;
nm = T.resolveExportNames();
coll1 = T.collisionInfo(nm);
check('auto-disambiguate clears collision', coll1[o2.id].size===0);
check('disambig names differ', nm[chr1.id]!==nm[chr1b.id], nm[chr1.id]+' / '+nm[chr1b.id]);
check('disambig uses source stem', nm[chr1b.id].includes('contig_collide'), nm[chr1b.id]);
T.autoDisambiguate = false;

console.log('\n[build FASTA]');
nm = T.resolveExportNames();
const fa1 = T.buildFasta(o1, nm);
check('o1 FASTA has 3 headers', (fa1.match(/^>/gm)||[]).length===3, (fa1.match(/^>/gm)||[]).length);
check('o1 FASTA wraps at 80', fa1.split('\n').every(l=>l.startsWith('>')||l.length<=80));
check('o1 FASTA header keeps desc', fa1.includes('>chr1 main chromosome'));

console.log('\n[build GFF + seqid rewrite]');
const gff1 = T.buildGff(o1, nm);
check('GFF starts with ##gff-version 3', gff1.startsWith('##gff-version 3'));
check('GFF has regenerated sequence-region chr1 1 120', gff1.includes('##sequence-region chr1 1 120'));
check('GFF has sequence-region pA 1 60', gff1.includes('##sequence-region pA 1 60'));
const featLines = gff1.split('\n').filter(l=>l && !l.startsWith('#'));
check('GFF carries 3 matched features (2 chr1 +1 pA)', featLines.length===3, featLines.length);
check('GFF excludes orphan ghost_seq', !gff1.includes('ghost_seq'));
check('GFF pB has no features (not in output dirs)', !gff1.includes('\tpB\t'));

// GFF with renamed seqid
T.autoDisambiguate = true;
nm = T.resolveExportNames();
const gff2 = T.buildGff(o2, nm);
const o2feat = gff2.split('\n').filter(l=>l && !l.startsWith('#'));
check('o2 GFF feature seqid rewritten to disambiguated name',
   o2feat.some(l=>l.split('\t')[0]===nm[chr1.id]) && o2feat.some(l=>l.split('\t')[0]===nm[chr1b.id]),
   o2feat.map(l=>l.split('\t')[0]).join(','));
T.autoDisambiguate = false;

console.log('\n[zip]');
// CRC32 known value: crc32("123456789") = 0xCBF43926
const crc = T.crc32(new TextEncoder().encode('123456789'));
check('crc32("123456789")==0xCBF43926', crc===0xCBF43926, crc.toString(16));
const blob = T.makeZip([{name:'a.txt', data:new TextEncoder().encode('hello')}]);
check('makeZip returns a Blob', blob && typeof blob.size==='number' && blob.size>0, blob && blob.size);
// verify zip signature
const buf = Buffer.from(await blob.arrayBuffer());
check('zip starts with PK\\x03\\x04', buf[0]===0x50&&buf[1]===0x4b&&buf[2]===0x03&&buf[3]===0x04);
check('zip ends with EOCD PK\\x05\\x06', buf.includes(Buffer.from([0x50,0x4b,0x05,0x06])));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
