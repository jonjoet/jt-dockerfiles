"""Deterministic small mixed-technology fixture; standard library only."""
from pathlib import Path
import random


def make_fixture(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(4917)
    sequences = {name: ''.join(rng.choices('ACGT', k=length))
                 for name, length in [('chr1', 12000), ('chr2', 7000)]}
    (root / 'reference.fasta').write_text(''.join(f'>{name}\n' + '\n'.join(seq[i:i+60] for i in range(0,len(seq),60)) + '\n'
                                               for name,seq in sequences.items()))
    (root / 'annotation.gff3').write_text('##gff-version 3\nchr2\tfixture\tgene\t101\t600\t.\t+\t.\tID=gene2;Name=beta\n'
                                         'chr1\tfixture\tgene\t101\t900\t.\t+\t.\tID=gene1;Name=alpha\n'
                                         '##FASTA\n>chr1\nACGT\n')
    def record(name,seq):
        return f'@{name}\n{seq}\n+\n'+ 'I'*len(seq)+'\n'
    def rc(seq):
        return seq.translate(str.maketrans('ACGT','TGCA'))[::-1]
    seq=sequences['chr1']
    (root/'single.fastq').write_text(record('single-map',seq[100:250])+record('single-unmapped','N'*150))
    (root/'r1.fastq').write_text(record('pair/1',seq[1000:1150])+record('unmapped/1','N'*150))
    (root/'r2.fastq').write_text(record('pair/2',rc(seq[1300:1450]))+record('unmapped/2','N'*150))
    (root/'interleaved.fastq').write_text(record('inter/1',seq[2000:2150])+record('inter/2',rc(seq[2300:2450])))
    (root/'nanopore.fastq').write_text(record('ont-map',seq[3000:4500])+record('ont-unmapped','N'*1500))
    (root/'read-groups.tsv').write_text('label\ttechnology\tlayout\tread1\tread2\n'
        'Short reads\tillumina\tsingle\tsingle.fastq\t\n'
        'Paired reads\tillumina\tpaired\tr1.fastq\tr2.fastq\n'
        'Interleaved reads\tillumina\tinterleaved\tinterleaved.fastq\t\n'
        'Long reads\tnanopore\tsingle\tnanopore.fastq\t\n')
    return root


if __name__ == '__main__':
    import sys
    make_fixture(sys.argv[1])
