"""Freeze the LLM input for exp14 reproducibility test.

Source: results/snapshots/repro_run3 (level-0 communities + 357 entities
+ level-0 community reports). The same frozen blob is fed to every run
so extraction variance is isolated out and we only measure step-3 LLM
variance.

Output: results/exp14_overlap200_stability/frozen_input.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

SNAPSHOT = Path('results/snapshots/repro_run3')
OUT = Path('results/exp14_overlap200_stability/frozen_input.json')


def build() -> dict:
    ents = pd.read_parquet(SNAPSHOT / 'entities.parquet')
    coms = pd.read_parquet(SNAPSHOT / 'communities.parquet')
    reps = pd.read_parquet(SNAPSHOT / 'community_reports.parquet')

    coms = coms[coms['level'] == 0].copy()
    reps = reps[reps['level'] == 0].copy()

    id_to_title = {str(r['id']): str(r['title']) for _, r in ents.iterrows()}

    entities_out = []
    for _, r in ents.iterrows():
        entities_out.append({
            'id': str(r['id']),
            'title': str(r['title']),
            'type': str(r['type']),
            'degree': int(r['degree']),
            'description': str(r['description']),
        })

    rep_by_community = {
        int(r['community']): {
            'title': str(r['title']),
            'summary': str(r['summary']),
            'rank': float(r['rank']) if pd.notna(r['rank']) else None,
        }
        for _, r in reps.iterrows()
    }

    communities_out = []
    covered_titles = set()
    for _, r in coms.iterrows():
        cid = int(r['community'])
        eids = [str(x) for x in r['entity_ids']]
        member_titles = [id_to_title[x] for x in eids if x in id_to_title]
        covered_titles.update(member_titles)
        rep = rep_by_community.get(cid, {})
        communities_out.append({
            'community_id': cid,
            'size': int(r['size']),
            'member_titles': member_titles,
            'report_title': rep.get('title'),
            'report_summary': rep.get('summary'),
            'report_rank': rep.get('rank'),
        })

    all_titles = {e['title'] for e in entities_out}
    uncovered = sorted(all_titles - covered_titles)

    blob = {
        'meta': {
            'snapshot': str(SNAPSHOT),
            'n_entities': len(entities_out),
            'n_communities_level0': len(communities_out),
            'n_reports_level0': len(reps),
            'uncovered_entities_count': len(uncovered),
        },
        'entities': entities_out,
        'communities': communities_out,
        'uncovered_entity_titles': uncovered,
    }
    return blob


def main() -> None:
    blob = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding='utf-8')
    m = blob['meta']
    print(f'wrote {OUT}')
    print(f'  entities={m["n_entities"]} communities(L0)={m["n_communities_level0"]} '
          f'reports(L0)={m["n_reports_level0"]} uncovered={m["uncovered_entities_count"]}')


if __name__ == '__main__':
    main()
