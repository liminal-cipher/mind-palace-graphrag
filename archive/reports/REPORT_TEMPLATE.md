## 리포트 작성 표준

리포트는 `archive/reports/` 아래에 `NN_<slug>.md` 형식(영문, 두 자리 숫자 접두)으로 둔다.
파일 맨 위에 YAML frontmatter(`---`로 감싼 블록)를 얹고, 그 아래는 자유 서술.

## 문서 type 3종

- **experiment**: 실험 1건 = 문서 1개. Notion DB 행이 된다. 표로 환원되는 핵심 수치를 frontmatter에 다 담아 한 줄로 비교 가능하게 한다.
- **synthesis**: 여러 experiment를 종합/해석. frontmatter는 type/id/date만. 본문은 자유.
- **spec**: 스펙·계약서·설계 문서(예: 데이터 계약서, 인터페이스 정의). frontmatter는 type/id/date만. 본문은 자유.

## frontmatter 필드

### experiment

```yaml
---
type: experiment
id: 00_baseline           # 파일명(확장자 빼고)과 동일
date: 2026-06-02
input: 파일명 (자수)       # 사용한 입력 자료
model: gpt-4.1-mini / text-embedding-3-small
variable: null             # 이 실험에서 baseline 대비 바꾼 것. baseline은 null
params:                    # 실험 설정 (entity_types, max_gleanings, use_lcc, max_cluster_size 등)
  use_lcc: false
  max_cluster_size: 10
entities: 385
relationships: 392
communities_total: 91
level0: 31
level1: 54
level2: 6
time_total_s: 963.9
cost_usd: $1.0153          # 문서 표기대로. 추가분이면 "+0.15" 식으로 그대로 둠
conclusion: 한 줄 결론
next: 다음에 해볼 것
snapshot: results/snapshots/<dir>   # 이 실험이 만든/사용한 스냅샷 경로. 없으면 null
---
```

규칙:
- 값이 문서에 없으면 `null`. 추정해서 채우지 말 것.
- `cost_usd`는 문서 표기 그대로. "전체 $1.02"인지 "+$0.15 추가"인지 구분이 분석에 중요하다.
- `variable`은 비교축이다. "baseline 대비 무엇이 달라졌나" 한 줄로.

### synthesis / spec

```yaml
---
type: synthesis    # 또는 spec
id: 03_repro_step3_summary
date: 2026-06-02
---
```

본문은 자유 서술. frontmatter는 최소만 둔다.
