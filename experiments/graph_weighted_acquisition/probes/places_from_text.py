"""Count who stands where in ordinary text (relate.places) and write the table.

    places_from_text.py <text: .parquet files with a `text` column, or a file of sentences> ... \
        --words packs/basic_words_ko.tsv --ends packs/word_ends_ko.tsv --out <table.tsv> [--sentences N]

The text and the table stay outside the repository. A sentence is a line cut at ". ".
"""
import argparse
import sys
import time

from experiments.graph_weighted_acquisition import basic as B
from experiments.graph_weighted_acquisition import relate as RL


def sentences(paths, limit):
    n = 0
    for path in paths:
        if path.endswith('.parquet'):
            import pyarrow.parquet as pq
            texts = (row for batch in pq.ParquetFile(path).iter_batches(batch_size=200, columns=['text'])
                     for row in batch.column('text').to_pylist())
        else:
            texts = open(path, encoding='utf8')
        for text in texts:
            for line in text.split('\n'):
                for sentence in line.split('. '):
                    if len(sentence.split()) >= 3:
                        yield sentence
                        n += 1
                        if n >= limit:
                            return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('text', nargs='+')
    ap.add_argument('--words', required=True)
    ap.add_argument('--ends', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--sentences', type=int, default=300000)
    args = ap.parse_args()
    start = time.time()
    table = RL.places(B.load(args.words, args.ends), sentences(args.text, args.sentences))
    RL.save(table, args.out)
    print('%d places, written to %s in %.0f s' % (len(table), args.out, time.time() - start), file=sys.stderr)


if __name__ == '__main__':
    main()
