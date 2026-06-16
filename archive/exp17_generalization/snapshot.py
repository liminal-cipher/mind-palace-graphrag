"""exp17 Phase B step 2: freeze graphrag output to snapshot/.

Layout mirrors results/snapshots/repro_run3/: entities, relationships,
text_units, documents, communities parquets + lancedb/ + context.json +
stats.json. community_reports is excluded (workflow disabled).

No transformation, just verbatim copy. Deterministic.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'output'
DST = ROOT / 'snapshot'

PARQUETS = [
    'entities.parquet',
    'relationships.parquet',
    'text_units.parquet',
    'documents.parquet',
    'communities.parquet',
]
OPTIONAL = [
    'context.json',
    'stats.json',
]


def main() -> None:
    if not SRC.exists():
        print(f'STOP: source output dir missing: {SRC}')
        sys.exit(2)
    DST.mkdir(parents=True, exist_ok=True)

    report = {'copied': [], 'skipped_missing': []}
    for name in PARQUETS:
        s, d = SRC / name, DST / name
        if not s.exists():
            print(f'STOP: required parquet missing: {s}')
            sys.exit(2)
        shutil.copy2(s, d)
        report['copied'].append(name)
    for name in OPTIONAL:
        s, d = SRC / name, DST / name
        if s.exists():
            shutil.copy2(s, d)
            report['copied'].append(name)
        else:
            report['skipped_missing'].append(name)

    lance_src = SRC / 'lancedb'
    lance_dst = DST / 'lancedb'
    if not lance_src.exists():
        print(f'STOP: lancedb dir missing: {lance_src}')
        sys.exit(2)
    if lance_dst.exists():
        shutil.rmtree(lance_dst)
    shutil.copytree(lance_src, lance_dst)
    report['lancedb'] = sorted(p.name for p in lance_dst.iterdir())

    (DST / 'snapshot_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
