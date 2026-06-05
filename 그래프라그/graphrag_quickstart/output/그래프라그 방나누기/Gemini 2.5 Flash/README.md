# 그래프 기반 방 나누기 결과

## 개요
한국사 조선·개화기 텍스트를 GraphRAG로 인덱싱하여 개념 간 관계 그래프를 구축하고,
Leiden 알고리즘으로 자동 커뮤니티(방)를 생성한 결과물.

## 이전 방식과의 차이
| | 요약 없이 바로 방 나누기 (이전) | 그래프 기반 방 나누기 (현재) |
|---|---|---|
| 분류 주체 | LLM이 전부 판단 | 알고리즘(Leiden)이 분류 |
| 근거 | LLM 판단 | 엔티티 간 실제 연결 관계 |
| 긴 문서 처리 | 컨텍스트 한계 있음 | 제한 없음 |
| 개념 간 연결선 | 없음 | 있음 (Three.js 연결 가능) |

## 사용 설정 (settings.yaml 핵심값)
- **entity_types**: `[인물, 사건, 정책, 문물, 서적, 기관, 장소]` — 한국사 맞춤 하드코딩
- **max_cluster_size**: `10` — 방 크기 조절 레버 (작을수록 방 많아짐)
- **chunk size**: `1200 tokens` / overlap `100 tokens`
- **모델**: Gemini 2.5 Flash (엔티티 추출, 커뮤니티 요약) + Gemini Embedding 001 (벡터화)

## 인덱싱 결과 수치 (한국사 조선·개화기 1단원)
- 추출된 엔티티: **58개**
- 추출된 관계: **72개**
- 생성된 커뮤니티(방): **13개** (level_0: 7개, level_1: 6개)

## 결과 파일 설명
| 파일 | 내용 |
|---|---|
| `entities.parquet` | 추출된 개념 목록 (이름, 타입, 설명) |
| `relationships.parquet` | 개념 간 관계 (Three.js 연결선으로 사용) |
| `communities.parquet` | 방 구조 — level_1 사용 권장 (10~20개 방) |
| `text_units.parquet` | 청킹된 원문 조각들 |

## 다음 단계
communities.parquet (level_1) → 변환 스크립트 → rooms JSON → Three.js 3D 기억의 궁전
