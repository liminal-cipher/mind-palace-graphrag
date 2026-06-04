"""실험 5 stage2 LLM 경로 v2 (assignment 방식). v1 partition과 모델, temperature,
페이로드, API 호출 구조까지 동일하게 두고 프롬프트와 파싱·검증만 바꾼다. v1과의
apples-to-apples 비교가 목적.

차이점은 두 가지뿐:
1) 프롬프트: "K개 그룹으로 분할하라"가 아니라 "방 40개 각각에 0..K-1 라벨을 매겨라".
   모델은 그룹을 짜는 게 아니라 라벨만 다니까 누락·중복이 구조적으로 거의 안 생긴다.
2) 파싱·검증: object_pairs_hook으로 중복 키를 잡고, 키 0~n-1 누락, dup, 값 범위 0..K-1,
   bad_keys를 따로 점검한다. 검증 실패 시 코드로 메우지 않고 그대로 실패로 기록한다.

파이프라인 단계: stage2(병합). K=5 고정, 같은 페이로드로 3런 독립 호출(재시도 피드백 없음).

핵심 입출력:
- 입력: results/snapshots/repro_run3/ (stage1을 거쳐 만든 텍스트 페이로드).
- 출력: results/exp5/stage2_llm_v2_K{K}_run{n}.json (검증 통과한 런만),
  llm_v2_reliability.json (3런 요약), llm_v2_raw/run{n}.txt (각 런 raw 응답, 파싱 전에 저장).
"""
from __future__ import annotations
import os, sys, io, json
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from openai import AzureOpenAI
from exp5_lib import (load_base, build_room_payloads, format_for_llm,
                      save_json, OUT)

API_VERSION = "2024-12-01-preview"
DEPLOYMENT = "gpt-4.1-mini"
K = 5
N_RUNS = 3
RAW_DIR = OUT / 'llm_v2_raw'
RAW_DIR.mkdir(parents=True, exist_ok=True)


def make_prompt(payload_text, K, n_rooms):
    """assignment 방식 system+user 프롬프트 생성. 출력은 {community_id: group_label} 형태의
    플랫 JSON 딕셔너리 하나로 강제하며, K개 라벨을 다 쓰지 않아도 valid로 본다."""
    sys_prompt = (
        f"당신은 한국사 교과서 분석가다. 아래 {n_rooms}개 방 각각에 "
        f"0~{K-1} 사이 그룹 번호를 하나씩 매겨라.\n"
        f"모든 방이 정확히 하나의 번호를 받아야 하고, 비슷한 주제끼리 같은 번호로 묶어라.\n"
        f"{K}개 그룹을 다 쓸 필요는 없다.\n"
        f"출력은 방 번호(community ID)를 키로, 그룹 번호를 값으로 하는 "
        f"JSON 딕셔너리 하나만, 다른 설명 없이: "
        f'{{"0": 2, "1": 0, ..., "{n_rooms-1}": 3}}'
    )
    user = "다음은 묶을 방 목록이다:\n\n" + payload_text
    return sys_prompt, user


def strip_code_fence(s):
    """앞뒤에 ```json ... ``` 코드펜스가 있으면 그것만 벗기고 내용은 그대로 둔다.
    response_format=json_object여도 일부 응답이 펜스를 붙여 나오는 케이스를 막기 위한 방어."""
    s = s.strip()
    if not s.startswith('```'):
        return s
    lines = s.split('\n')
    lines = lines[1:]
    if lines and lines[-1].strip().startswith('```'):
        lines = lines[:-1]
    return '\n'.join(lines).strip()


def parse_pairs(raw):
    """JSON 파싱하되 dup key를 살려서 모든 (key, value) pair 수집.
    파싱 실패면 (None, err) 반환.

    함정: json.loads를 그냥 돌리면 같은 키가 두 번 등장해도 dict가 두 번째 값으로 조용히
    덮어써서 중복이 안 잡힌다. object_pairs_hook으로 파서가 받은 (key, value) 시퀀스를
    직접 받아야 dup이 보존된다."""
    txt = strip_code_fence(raw)
    captured = []

    def hook(items):
        captured.extend(items)
        return dict(items)

    try:
        json.loads(txt, object_pairs_hook=hook)
    except Exception as e:
        return None, f'json parse: {type(e).__name__}: {e}'
    return captured, None


def validate_assignment(pairs, expected_cnums, K):
    """assignment 검증. (키, 값) 페어 리스트를 받아 다음을 모두 확인하고 dict로 돌려준다:
    missing(빠진 community), dup(같은 키가 두 번 이상), out_of_range(값이 0..K-1 밖),
    bad_keys(정수로 못 바꾸는 키). valid는 이 모두가 0이고 고유 키 수가 community 수와
    같을 때만 True. K개 라벨 중 일부만 써도 valid는 살아 있다."""
    expected_set = set(int(c) for c in expected_cnums)

    seen_int_keys = []
    bad_keys = []
    for k, _ in pairs:
        try:
            seen_int_keys.append(int(k))
        except (ValueError, TypeError):
            bad_keys.append(k)

    cnt = Counter(seen_int_keys)
    dup = sorted([k for k, n in cnt.items() if n > 1])
    unique_keys = set(seen_int_keys)
    missing = sorted(expected_set - unique_keys)

    out_of_range = []
    for k, v in pairs:
        try:
            iv = int(v)
        except (ValueError, TypeError):
            out_of_range.append([k, v])
            continue
        if iv < 0 or iv >= K:
            out_of_range.append([k, iv])

    valid = (
        not missing
        and not dup
        and not out_of_range
        and not bad_keys
        and len(unique_keys) == len(expected_set)
    )
    return {
        'valid': valid,
        'missing': missing,
        'dup': dup,
        'out_of_range': out_of_range,
        'bad_keys': bad_keys,
        'unique_keys': len(unique_keys),
    }


def labels_used(pairs):
    """페어에 실제로 등장한 그룹 라벨의 정렬된 리스트. 값이 정수 변환 불가하면 건너뛴다.
    K개 중 몇 개를 실제로 썼는지(groups_used) 집계용."""
    labels = set()
    for _, v in pairs:
        try:
            labels.add(int(v))
        except (ValueError, TypeError):
            pass
    return sorted(labels)


def build_merge_result(pairs, run_n, expected_cnums):
    """검증을 통과한 페어를 stage2 MergeResult 스키마로 변환.
    K 필드에는 요청한 K가 아니라 실제로 등장한 라벨 수(=len(groups))를 넣는다.
    네이밍은 stage3 borrow_name이 처리하므로 new_title은 일단 null."""
    groups = defaultdict(list)
    for k, v in pairs:
        groups[int(v)].append(int(k))
    merged_rooms = []
    for label in sorted(groups.keys()):
        merged_rooms.append({
            'new_id': int(label),
            'members': sorted(groups[label]),
            'new_title': None,
            'silhouette': None,
        })
    return {
        'method': 'llm_v2',
        'run': run_n,
        'K': len(groups),
        'merged_rooms': merged_rooms,
    }


def call_once(client, sys_p, user_p):
    """Azure OpenAI 한 번 호출. (raw 문자열, usage dict) 반환.
    재시도·피드백 없음. 3런 모두 같은 sys_p/user_p로 독립 호출하기 위해 일부러 단순화."""
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{'role': 'system', 'content': sys_p},
                  {'role': 'user', 'content': user_p}],
        temperature=0,
        response_format={'type': 'json_object'},
    )
    raw = resp.choices[0].message.content
    usage = {'prompt_tokens': resp.usage.prompt_tokens,
             'completion_tokens': resp.usage.completion_tokens}
    return raw, usage


if __name__ == '__main__':
    api_key = os.environ.get('GRAPHRAG_API_KEY')
    if not api_key:
        raise SystemExit('GRAPHRAG_API_KEY 환경 변수 없음')
    azure_endpoint = os.environ.get('GRAPHRAG_API_BASE')
    if not azure_endpoint:
        raise SystemExit('GRAPHRAG_API_BASE 환경 변수 없음')

    ent, com_l0, rep_l0 = load_base()
    ROOMS = build_room_payloads(ent, com_l0, rep_l0)
    n_rooms = len(ROOMS)
    print(f'rooms: {n_rooms}')

    payload_text = format_for_llm(ROOMS)
    all_cnums = [r['community'] for r in ROOMS]

    client = AzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        api_version=API_VERSION,
    )

    sys_p, user_p = make_prompt(payload_text, K, n_rooms)

    reliability = {}
    for run_n in range(1, N_RUNS + 1):
        print(f'\n=== llm_v2 run{run_n} (K={K}) ===')
        raw, usage = call_once(client, sys_p, user_p)
        (RAW_DIR / f'run{run_n}.txt').write_text(raw, encoding='utf-8')
        print(f'  raw saved: {RAW_DIR}/run{run_n}.txt ({len(raw)} chars)')
        print(f'  usage: prompt={usage["prompt_tokens"]} '
              f'completion={usage["completion_tokens"]}')

        pairs, parse_err = parse_pairs(raw)
        if pairs is None:
            entry = {
                'parsed': False,
                'valid': False,
                'parse_error': parse_err,
                'groups_used': 0,
                'missing': None,
                'dup': None,
                'out_of_range': None,
                'usage': usage,
            }
            print(f'  parsed=False ({parse_err})')
        else:
            v = validate_assignment(pairs, all_cnums, K)
            used = labels_used(pairs)
            entry = {
                'parsed': True,
                'valid': v['valid'],
                'groups_used': len(used),
                'labels_used': used,
                'missing': v['missing'],
                'dup': v['dup'],
                'out_of_range': v['out_of_range'],
                'bad_keys': v['bad_keys'],
                'unique_keys': v['unique_keys'],
                'usage': usage,
            }
            print(f"  parsed=True valid={v['valid']} "
                  f"groups_used={len(used)} missing={v['missing']} "
                  f"dup={v['dup']} oor={v['out_of_range']}")
            if v['valid']:
                mr = build_merge_result(pairs, run_n, all_cnums)
                out_path = OUT / f'stage2_llm_v2_K{K}_run{run_n}.json'
                save_json(out_path, mr)
                print(f'  stage2 saved: {out_path}')

        reliability[f'run{run_n}'] = entry

    summary_path = OUT / 'llm_v2_reliability.json'
    save_json(summary_path, {
        'method': 'llm_v2',
        'K_requested': K,
        'n_rooms': n_rooms,
        'runs': reliability,
    })
    print(f'\nreliability saved: {summary_path}')

    passed = sum(1 for r in reliability.values() if r.get('valid'))
    print(f'\nGATE: {passed}/{N_RUNS} runs valid')
