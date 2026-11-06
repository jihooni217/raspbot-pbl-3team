#!/usr/bin/env python3
# 지시서: specs/08-command.md
"""실제08 CLI의 --dry-run으로 고정18문장을 비교한다. 장치 실행 없음."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/command'
CASES = OUT/'cases.json'


def summaries():
    all_rows = {}
    for mode in ('ai','keyword'):
        rows = {}
        path = OUT/f'trial_{mode}.jsonl'
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line);rows[row['index']] = row
        all_rows[mode] = rows
    summary = {}
    for mode,rows in all_rows.items():
        groups = {}
        for group in ('example','refusal','paraphrase'):
            subset = [r for r in rows.values() if r['case']['group']==group]
            groups[group] = dict(correct=sum(r['matched'] for r in subset),tested=len(subset))
        summary[mode] = dict(groups=groups,total_tested=len(rows),
            actual_ai=sum(r['record'].get('source')=='ai' for r in rows.values()),
            fallbacks=sum(r['record'].get('fallback',False) for r in rows.values()),
            max_wall_seconds=max((r['wall_seconds'] for r in rows.values()),default=0),
            over_20_seconds=sum(r['wall_seconds']>20 for r in rows.values()))
    (OUT/'trial_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('ai','keyword'),required=True)
    parser.add_argument('--start',type=int,default=0)
    parser.add_argument('--end',type=int,default=18)
    args = parser.parse_args()
    cases = json.loads(CASES.read_text())
    for index in range(args.start,min(args.end,len(cases))):
        case = cases[index]
        argv = [sys.executable,str(ROOT/'missions/08_command.py'),'--dry-run','--json']
        if args.mode=='keyword':argv.append('--keywords-only')
        argv.append(case['text'])
        started = time.monotonic()
        source_sha = hashlib.sha256((ROOT/'missions/08_command.py').read_bytes()).hexdigest()
        print(f'{args.mode} {index+1}/18: {case["text"]}',flush=True)
        result = subprocess.run(argv,cwd=ROOT,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=23,
                                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        elapsed = time.monotonic()-started
        if result.returncode:raise RuntimeError(result.stderr[-2000:])
        record = json.loads(result.stdout)
        assert record['dry_run'] is True and record['result']['status']=='DRY_RUN'
        matched = record['command']['action']==case['action'] and all(record['command'].get(k)==v for k,v in case.items() if k not in ('action','text','group'))
        row = dict(index=index,mode=args.mode,case=case,record=record,matched=matched,
                   wall_seconds=round(elapsed,4),time=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                   cases_sha256=hashlib.sha256(CASES.read_bytes()).hexdigest(),
                   source_sha256=source_sha)
        with (OUT/f'trial_{args.mode}.jsonl').open('a') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(f" -> {record['command']['action']} ({record['source']}, fallback={record['fallback']}) {elapsed:.2f}s {'PASS' if matched else 'FAIL'}",flush=True)
    summaries()


if __name__ == '__main__':
    main()
