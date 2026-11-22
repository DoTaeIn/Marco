"""Run isolated v2 induction and held-out admission with user-supplied datasets."""
import argparse
import json
from pathlib import Path
from . import v2


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--train',required=True); parser.add_argument('--dev',required=True)
    parser.add_argument('--output',required=True); parser.add_argument('--contrasts')
    parser.add_argument('--max-proposals',type=int,default=v2.MAX_LOOP_PROPOSALS); parser.add_argument('--max-rounds',type=int,default=v2.MAX_LOOP_ROUNDS)
    args=parser.parse_args()
    train=json.loads(Path(args.train).read_text(encoding='utf8'))
    dev=json.loads(Path(args.dev).read_text(encoding='utf8'))
    # Training sees examples only; no pair answers flow into grammar induction.
    contrasts=json.loads(Path(args.contrasts).read_text(encoding='utf8'))['contrasts'] if args.contrasts else dev.get('contrasts',[])
    result=v2.acquire_incremental(train['examples'],dev['examples'],dev['pairs'],contrasts,max_proposals=args.max_proposals,max_rounds=args.max_rounds)
    learned=result['learning']; report=result['admission']
    baseline=set(dev.get('baseline_correct',[]))
    if not baseline.issubset({r['id'] for r in report['dev'] if r['correct']}):
        report['admitted']=False; report['reasons'].append('external previous-dev baseline regression')
    Path(args.output).write_text(json.dumps({'version':'example-acquisition-report-v2','learning':learned,'admission':report},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('admitted' if report['admitted'] else 'held')


if __name__=='__main__': main()
