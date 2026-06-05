# GraphRAG 파라미터 튜닝 결과 정리 (1~9차)

## 최종 결론
**9차: use_lcc: true 적용 → level_0 16개 달성** ✅

---

## 1. 전체 비교표

| 차수 | entity_types | max_cluster_size | resolution | use_lcc | temperature | 엔티티 | 관계 | 전체 커뮤니티 | level_0 | 특징 |
|------|--------------|------------------|-----------|---------|------------|--------|------|-------------|---------|------|
| **1차** | 7개 | 10 | - | false | 기본 | 894 | 1207 | 236 | ? | 초기값, 기본 설정 |
| **2차** | 7개 | 10 | - | false | 기본 | 617 | 803 | 59 | 32 | max_gleanings: 0 적용 |
| **3차** | 7개 | 40 | - | false | 기본 | 617 | 803 | 59 | 32 | max_cluster_size: 40 |
| **4차 재** | 5개 | 40 | - | false | 0.0 | 504 | 588 | 48 | 36 ↑ | entity_types 축소, 캐시 초기화 |
| **5차** | 3개 | 40 | - | false | 0.0 | ? | ? | ? | 57+ ↑ | entity_types: 3개 (역효과) |
| **6차** | 5개 | 80 | - | false | 0.0 | ? | ? | ? | 40+ | max_cluster_size: 80 |
| **7차** | 5개 | 100 | - | false | 0.0 | ? | ? | ? | 33 | max_cluster_size: 100 (최저) |
| **8차** | 5개 | 80 | 0.1 | false | 0.0 | 468 | 570 | 36 | 36 | resolution: 0.1 추가 (효과 없음) |
| **9차 ✅** | 5개 | 80 | - | **true** | 0.0 | 468 | 549 | 16 | **16** | **use_lcc: true 적용** |

---

## 2. 설정별 상세 분석

### 1차: 초기값 (기본)
```yaml
entity_types: [인물, 사건, 정책, 문물, 서적, 기관, 장소]  # 7개
max_gleanings: 2  # 기본값
max_cluster_size: 10  # 기본값
temperature: 기본값
```
**결과**: 엔티티 894개, 커뮤니티 236개 (너무 많음)

---

### 2차: max_gleanings: 0
```yaml
entity_types: [인물, 사건, 정책, 문물, 서적, 기관, 장소]  # 7개
max_gleanings: 0  # ← 변경 (LLM 재시도 제거)
max_cluster_size: 10
temperature: 기본값
```
**결과**: 엔티티 617개, 커뮤니티 59개, level_0: 32개
**발견**: max_gleanings 축소로 엔티티 27% 감소

---

### 3차: max_cluster_size: 40
```yaml
entity_types: [인물, 사건, 정책, 문물, 서적, 기관, 장소]  # 7개
max_gleanings: 0
max_cluster_size: 40  # ← 변경 (10 → 40)
temperature: 기본값
```
**결과**: 엔티티 617개, 커뮤니티 59개, level_0: 32개
**발견**: max_cluster_size 증가해도 변화 없음 (네트워크 구조 안 변함)

---

### 4차 재실행: 캐시 초기화 + entity_types 축소 + temperature
```yaml
entity_types: [인물, 사건, 기관, 정책, 장소]  # 5개 (문물, 서적 제거)
max_gleanings: 0
max_cluster_size: 40
temperature: 0.0  # ← 변경 (결정적 결과)
# 캐시 초기화: rm -r cache
```
**결과**: 엔티티 504개, 관계 588개, 커뮤니티 48개, level_0: 36개 ↑
**발견**: entity_types 축소 역효과! (32 → 36)
- 엔티티 수는 줄었지만 관계 네트워크 변화로 커뮤니티 증가

---

### 5차: entity_types 더 축소
```yaml
entity_types: [인물, 사건, 기관]  # 3개 (정책, 문물 제거)
max_gleanings: 0
max_cluster_size: 40
temperature: 0.0
```
**결과**: 전체 커뮤니티 57개, level_0: 57개+ ↑↑
**발견**: entity_types 축소는 역효과 심화!
- 더 축소할수록 커뮤니티 증가

---

### 6차: max_cluster_size: 80
```yaml
entity_types: [인물, 사건, 정책, 문물, 기관]  # 5개로 되돌림
max_gleanings: 0
max_cluster_size: 80  # ← 변경 (40 → 80)
temperature: 0.0
```
**결과**: level_0: 40개+
**발견**: max_cluster_size 증가도 일관성 없음

---

### 7차: max_cluster_size: 100
```yaml
entity_types: [인물, 사건, 정책, 문물, 기관]  # 5개
max_gleanings: 0
max_cluster_size: 100  # ← 변경 (80 → 100)
temperature: 0.0
```
**결과**: level_0: 33개 ↓
**발견**: 역설적으로 가장 작은 결과
- max_cluster_size 증가가 항상 커뮤니티 감소를 의미하지 않음

---

### 8차: resolution: 0.1
```yaml
entity_types: [인물, 사건, 정책, 문물, 기관]  # 5개
max_gleanings: 0
max_cluster_size: 80  # 7차에서 80으로 되돌림
resolution: 0.1  # ← 추가 (Leiden 분해도)
use_lcc: false
temperature: 0.0
```
**결과**: 엔티티 468개, 관계 570개, level_0: 36개
**발견**: resolution 효과 없음 (8차와 4차 같은 수준)

---

### 9차 ✅: use_lcc: true (최종 선정)
```yaml
entity_types: [인물, 사건, 정책, 문물, 기관]  # 5개
max_gleanings: 0
max_cluster_size: 80
use_lcc: true  # ← 핵심 변경! (false → true)
temperature: 0.0
```
**결과**: 엔티티 468개, 관계 549개, level_0: **16개** ✅
**발견**: **use_lcc: true가 해결책!**
- 연결 안 된 작은 그래프 제거
- 36 → 16으로 대폭 감소 (55% 감소)
- level_0만 존재 (level_1 없음)

---

## 3. 핵심 학습 정리

### ❌ 효과 없거나 역효과인 것들
| 파라미터 | 시도 | 결과 | 이유 |
|---------|------|------|------|
| entity_types 축소 | 7개→5개→3개 | 32→36→57+ | 네트워크 구조 급변으로 Leiden 재분할 |
| max_cluster_size 증가 | 10→40→80→100 | 일관성 없음 | 단일 파라미터로 충분하지 않음 |
| resolution 추가 | 0.1 설정 | 36→36 (효과 없음) | Leiden 내부 파라미터 효과 제한적 |
| temperature 기본값 | 기본→0.0 | 약간 효과 | 효과는 있지만 단독 해결책 아님 |

### ✅ 효과 있는 것들
| 파라미터 | 변경 | 효과 | 이유 |
|---------|------|------|------|
| **use_lcc** | false→true | 36→16 (55% 감소) | 핵심 해결책! 연결된 요소만 유지 |
| max_gleanings | 2→0 | 894→617 (27% 감소) | LLM 재시도 제거로 엔티티 수 감소 |
| temperature | 기본→0.0 | 일관성 증가 | 결정적 결과 보장 |

---

## 4. 9차 최종 설정 정리

### settings.yaml
```yaml
completion_models:
  default_completion_model:
    temperature: 0.0

extract_graph:
  entity_types: [인물, 사건, 정책, 문물, 기관]
  max_gleanings: 0

cluster_graph:
  max_cluster_size: 80
  use_lcc: true  # ← 핵심!
```

### 실행 명령어
```bash
rm -r cache  # 캐시 초기화
cd graphrag_quickstart
graphrag index --root .
python read_results.py
```

### 최종 결과
```
엔티티: 468개
관계: 549개
전체 커뮤니티: 16개
level_0: 16개 (방)
level_1: 0개
```

---

## 5. 다음 단계

### 10차 옵션 (더 줄이고 싶다면)
- max_cluster_size를 120, 150으로 더 증가
- 또는 다른 파라미터 조합 시도

### 현재 선택지
- **A**: 16개로 진행 (Three.js 3D 시각화)
- **B**: 10차 진행해서 더 줄이기

---

## 파일 생성일
2026-06-02 (9차 완료 후)
