"""Compare fresh-process startup with the preserved pre-change runtime.
python -m mrl.benchmark_startup --sizes 10000 100000 1000000 --samples 5
OS file cache is not flushed. Compile/input generation are excluded.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from mrl.benchmark_ninth_restart import HEADERS, ROOT, source, summary
from mrl.toolchain import build_c


def benchmark_source(runtime):
    code = source(runtime)
    code = code.replace('if(argc!=5)return 1;', 'if(argc<5||argc>6)return 1;if(!strcmp(argv[1],"empty")){puts("READY");puts("{}");return 0;}int delta=argc==6?atoi(argv[5]):1;')
    code = code.replace('expected+=2;', 'expected+=2*delta;')
    code = code.replace('if(!mrl_horn_plan_add(&p,"added","new","p","tail",true,"asserted",(MrlHornEvidence){0}))return 5;', 'for(int i=0;i<delta;i++){char id[32],subject[32];snprintf(id,sizeof(id),"added%d",i);snprintf(subject,sizeof(subject),"new%d",i);if(!mrl_horn_plan_add(&p,id,subject,"p","tail",true,"asserted",(MrlHornEvidence){0}))return 5;}')
    return code


def run(exe, mode, data, checkpoint, n, delta):
    start = time.perf_counter()
    process = subprocess.Popen([str(exe), mode, str(data), str(checkpoint), str(n), str(delta)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
    ready = process.stdout.readline()
    first = (time.perf_counter() - start) * 1000
    output, error = process.communicate(timeout=180)
    if process.returncode or ready.strip() != 'READY':
        raise RuntimeError(f'{mode}/{n}: {process.returncode}: {ready} {error}')
    row = json.loads(output)
    row['process_to_first_answer_ms'] = first
    row['process_wall_ms'] = (time.perf_counter() - start) * 1000
    if mode != 'empty':
        assert row['fact_count'] == 2 * (n + (delta if mode == 'journal' else 0)), row
        if mode != 'load':
            assert row['cache_hit'] == 1, row
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sizes', nargs='+', type=int, default=[10000, 100000, 1000000])
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--baseline', type=Path, default=ROOT / 'docs/STARTUP_BASELINE.zip')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/STARTUP_BENCHMARK.json')
    args = parser.parse_args()
    if args.samples < 1 or any(n < 1 or n > 10000000 for n in args.sizes):
        parser.error('positive samples and sizes in 1..10000000 are required')
    report = {'samples': args.samples, 'boundary': 'Fresh native process to first verified count received by parent. OS file cache is not flushed. Compile and JSONL generation excluded. Workload N unique asserted triples, p->q produces 2N results. Delta is max(1,N/100) new facts committed without re-saving the prepared cache. Before/after order alternates by sample.', 'p95_method': 'nearest rank; five samples is not a reliable tail-latency estimate', 'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'baseline_archive_sha256': hashlib.sha256(args.baseline.read_bytes()).hexdigest(), 'source_sha256': {}, 'empty': {}, 'sizes': {}}
    with tempfile.TemporaryDirectory(prefix='mrl-startup-') as temporary:
        directory = Path(temporary)
        before = directory / 'before'; before.mkdir()
        with zipfile.ZipFile(args.baseline) as archive:
            expected = json.loads(archive.read('sha256.json'))
            for name in HEADERS:
                content = archive.read(name)
                assert hashlib.sha256(content).hexdigest() == expected[name], name
                (before / name).write_bytes(content)
        executables = {}
        for label, runtime in [('before', before), ('after', ROOT / 'runtime')]:
            report['source_sha256'][label] = {name: hashlib.sha256((runtime / name).read_bytes()).hexdigest() for name in HEADERS}
            c, exe = directory / f'{label}.c', directory / f'{label}.exe'
            c.write_text(benchmark_source(runtime), encoding='utf-8')
            try:
                build_c(c, exe)
            except subprocess.CalledProcessError as error:
                raise RuntimeError(error.stderr.decode(errors='replace')) from error
            executables[label] = exe
            report['empty'][label] = summary([run(exe, 'empty', '', '', 1, 1) for _ in range(args.samples)])
        for n in args.sizes:
            data = directory / f'{n}.jsonl'
            with data.open('w', encoding='utf-8', newline='\n') as stream:
                for i in range(n):
                    stream.write(json.dumps({'id': f'f{i}', 'triple': [f's{i}', 'p', f'o{i}']}, separators=(',', ':')) + '\n')
            delta = max(1, n // 100)
            rows = {label: {mode: [] for mode in ['load', 'restore', 'edit', 'journal']} for label in executables}
            for sample in range(args.samples):
                labels = ['before', 'after'] if sample % 2 == 0 else ['after', 'before']
                for label in labels:
                    checkpoint = directory / f'{label}-{n}-{sample}.bin'
                    for mode in rows[label]:
                        row = run(executables[label], mode, data, checkpoint, n, delta)
                        rows[label][mode].append(row)
                    print(f'{n} sample {sample+1}/{args.samples} {label}: restore {rows[label]["restore"][-1]["process_to_first_answer_ms"]:.2f} ms; journal {rows[label]["journal"][-1]["process_to_first_answer_ms"]:.2f} ms', flush=True)
            report['sizes'][str(n)] = {'delta_facts': delta, **{label: {mode: summary(values) for mode, values in modes.items()} for label, modes in rows.items()}}
            args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(args.output, flush=True)


if __name__ == '__main__':
    main()
