"""실험 5 stage2 LLM 경로 v1 (partition 방식). gpt-4.1-mini에 방 40개를 한꺼번에 주고
"정확히 K개 그룹으로 완전 분할하고 각 그룹의 members를 다 나열하라"고 시켜 MergeResult를 만든다.

파이프라인 단계: stage2(병합). stage1 페이로드(format_for_llm)를 그대로 입력으로 받는다.

K=5, K=8 각각에 대해 run_a/run_b 두 번 호출하고, 검증 실패 시 같은 호출 안에서 피드백을 붙여
최대 4회까지 재시도한다. 두 run이 모두 성공하면 partition_signature로 분할이 동일한지 비교한다.

핵심 입출력:
- 입력: results/snapshots/repro_run3/ (stage1을 거쳐 만든 텍스트 페이로드).
- 출력: results/exp5/stage2_llm_K{K}_{run_a,run_b}.json (검증 통과 시), llm_reliability.json
  (K별 두 런의 시도 로그와 재현성 결과). 또한 같은 디렉터리에 input_payload.txt와
  stage1_payloads.json도 감사용으로 남긴다.

관찰된 한계: 이 방식은 모든 시도(K=5/8 × run_a/run_b × 최대 4회)에서 누락·중복이 발생해
실제로는 stage2 산출이 만들어지지 않았다. 같은 페이로드를 assignment 방식으로 다시 푸는
경로는 exp5_llm_v2.py 참고.
"""
from __future__ import annotations
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from openai import AzureOpenAI
from exp5_lib import (load_base, build_room_payloads, format_for_llm,
                      validate_grouping, save_json, load_json, OUT)

API_VERSION = "2024-12-01-preview"
DEPLOYMENT = "gpt-4.1-mini"


def make_prompt(payload_text, K, all_cnums, feedback=None):
    """partition 방식 system+user 프롬프트 생성. feedback이 주어지면 user 메시지 끝에
    이전 시도의 누락/중복 정보를 덧붙인다. 같은 호출의 재시도에서 prompt가 매번
    바뀌기 때문에 temperature=0이어도 응답이 흔들릴 수 있다."""
    cnum_list_str = ', '.join(str(c) for c in sorted(all_cnums))
    sys_prompt = f"""당신은 한국사 교과서 분석가다. 주어진 방(그래프 커뮤니티) 목록을
의미가 가까운 것끼리 묶어 **정확히 {K}개**의 새 그룹으로 만든다.

규칙:
- 입력 community ID는 다음 {len(all_cnums)}개 정수다: [{cnum_list_str}]
- 출력 members의 합은 **반드시 위 {len(all_cnums)}개 전체와 동일**해야 한다. 누락·중복 금지.
- 시대·주제·인물·사건 관계를 보고 자연스럽게 묶는다.
- new_id는 0..{K-1}.
- new_title은 묶인 방들을 포괄하는 짧은 한국어 (20자 이내).

출력은 JSON만 (배열 길이 = {K}):
{{"merged_rooms": [{{"new_id": 0, "new_title": "...", "members": [c, c, ...]}}, ...]}}
"""
    user = "다음은 묶을 방 목록이다:\n\n" + payload_text + \
           f"\n\n위 {len(all_cnums)}개 방을 정확히 {K}개 그룹으로 완전 분할하라."
    if feedback:
        user += f"\n\n[이전 시도 피드백] {feedback}"
    return sys_prompt, user


def call_llm(client, payload_text, K, all_cnums, max_retry=4):
    """K=정수 그룹 분할 시도. 성공/실패 + 시도별 검증 결과를 모두 반환.
    실패해도 예외 던지지 않음 (호출자가 실패 K도 측정 대상으로 다룸)."""
    attempts_log = []
    feedback = None
    success = None
    for attempt in range(1, max_retry + 1):
        sys_p, user_p = make_prompt(payload_text, K, all_cnums, feedback)
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
        try:
            data = json.loads(raw)
        except Exception as e:
            attempts_log.append({'attempt': attempt, 'ok': False,
                                 'error': f'json parse: {e}', 'usage': usage})
            feedback = f'JSON 파싱 실패. 유효한 JSON object만 출력.'
            continue
        groups = data.get('merged_rooms', [])
        v = validate_grouping(groups, all_cnums, K)
        attempts_log.append({
            'attempt': attempt, 'ok': v['ok'],
            'missing': v['missing'], 'duplicate': v['duplicate'],
            'K_actual': v['K_actual'], 'usage': usage,
        })
        if v['ok']:
            success = {'attempt': attempt, 'raw': raw, 'groups': groups,
                       'validation': v, 'usage': usage}
            print(f"  attempt {attempt}: OK")
            break
        feedback = (f"누락된 community: {v['missing']}, 중복: {v['duplicate']}, "
                    f"받은 그룹 수: {v['K_actual']} (요청 {K}). 다음 시도에서 반드시 수정.")
        print(f"  attempt {attempt} 실패: missing={v['missing']}, "
              f"dup={v['duplicate']}, K_actual={v['K_actual']}")
    return {'success': success, 'attempts': attempts_log,
            'final_ok': success is not None}


def partition_signature(merged_rooms):
    """분할 비교용 정규화. 그룹 id와 LLM 제안 이름은 무시하고 멤버 community 집합의
    집합(frozenset of frozensets)으로만 비교한다. 두 run의 그룹 라벨 순서가 달라도
    같은 분할이면 같은 signature가 된다."""
    return frozenset(frozenset(g['members']) for g in merged_rooms)


def compare_partitions(rooms_a, rooms_b):
    """run_a, run_b의 merged_rooms를 받아 같은 분할인지 비교.
    {'same_partition': bool, 'only_in_a': [...], 'only_in_b': [...]} 반환."""
    pa = partition_signature(rooms_a)
    pb = partition_signature(rooms_b)
    return {
        'same_partition': pa == pb,
        'only_in_a': [sorted(s) for s in (pa - pb)],
        'only_in_b': [sorted(s) for s in (pb - pa)],
    }


def build_stage2(K, llm_success, run_label='run_a'):
    """검증을 통과한 LLM 응답을 stage2 MergeResult 스키마로 정규화.
    LLM이 제안한 new_title은 llm_suggested_title 필드에만 저장하고 정식 네이밍에는
    쓰지 않는다(설계 결정에 따라 네이밍은 stage3 borrow_name이 별도로 수행)."""
    return {
        'method': f'llm_K{K}_{run_label}',
        'K': K,
        'attempt_to_success': llm_success['attempt'],
        'usage': llm_success['usage'],
        'merged_rooms': [
            {
                'new_id': g['new_id'],
                'members': sorted(g['members']),
                'llm_suggested_title': g.get('new_title'),
                'silhouette': None,
            }
            for g in llm_success['groups']
        ],
    }


if __name__ == '__main__':
    api_key = os.environ.get('GRAPHRAG_API_KEY')
    if not api_key:
        raise SystemExit('GRAPHRAG_API_KEY 환경 변수 없음')
    azure_endpoint = os.environ.get('GRAPHRAG_API_BASE')
    if not azure_endpoint:
        raise SystemExit('GRAPHRAG_API_BASE 환경 변수 없음')

    ent, com_l0, rep_l0 = load_base()
    ROOMS = build_room_payloads(ent, com_l0, rep_l0)
    print(f'rooms: {len(ROOMS)}')

    # 페이로드 텍스트 저장 (감사용)
    payload_text = format_for_llm(ROOMS)
    (OUT / 'input_payload.txt').write_text(payload_text, encoding='utf-8')
    print(f'payload text chars: {len(payload_text)}')

    # RoomPayload JSON 저장 (단계 1 산출)
    save_json(OUT / 'stage1_payloads.json', ROOMS)
    print(f'stage1 saved: {OUT}/stage1_payloads.json')

    client = AzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        api_version=API_VERSION,
    )

    all_cnums = [r['community'] for r in ROOMS]
    reliability = {}  # K → {run_a: {...}, run_b: {...}, reproducibility: {...}}

    for K in [5, 8]:
        per_K = {}
        for run_label in ['run_a', 'run_b']:
            print(f'\n=== LLM 병합 K={K} / {run_label} ===')
            result = call_llm(client, payload_text, K, all_cnums)
            per_K[run_label] = {
                'final_ok': result['final_ok'],
                'attempts': result['attempts'],
            }
            if result['final_ok']:
                stage2 = build_stage2(K, result['success'], run_label)
                save_json(OUT / f'stage2_llm_K{K}_{run_label}.json', stage2)
                print(f'  → 성공 (시도 {result["success"]["attempt"]}회)')
                for g in stage2['merged_rooms']:
                    print(f"    new_id={g['new_id']} | "
                          f"LLM 제안={g['llm_suggested_title']} | "
                          f"members={g['members']}")
            else:
                print(f'  → 최종 실패 (모든 {len(result["attempts"])}회 검증 실패)')

        # 두 run이 모두 성공이면 분할 비교
        if per_K['run_a']['final_ok'] and per_K['run_b']['final_ok']:
            a = load_json(OUT / f'stage2_llm_K{K}_run_a.json')['merged_rooms']
            b = load_json(OUT / f'stage2_llm_K{K}_run_b.json')['merged_rooms']
            per_K['reproducibility'] = compare_partitions(a, b)
            print(f"  재현성 (run_a vs run_b): "
                  f"same_partition={per_K['reproducibility']['same_partition']}")
            if not per_K['reproducibility']['same_partition']:
                print(f"    run_a 고유 그룹: {per_K['reproducibility']['only_in_a']}")
                print(f"    run_b 고유 그룹: {per_K['reproducibility']['only_in_b']}")
        else:
            per_K['reproducibility'] = {
                'same_partition': None,
                'note': 'one or both runs failed',
            }
        reliability[K] = per_K

    save_json(OUT / 'llm_reliability.json', reliability)
    print(f"\nreliability saved: {OUT}/llm_reliability.json")
