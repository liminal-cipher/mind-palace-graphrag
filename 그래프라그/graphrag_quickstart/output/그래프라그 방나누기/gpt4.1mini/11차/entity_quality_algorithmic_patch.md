# Entity Quality Algorithmic Patch

LLM 없이 생성한 안전 병합/약한 관계 보강안입니다. 원본 parquet은 수정하지 않았습니다.

## Summary

- entity_count_before: 394
- safe_resolution_group_count: 4
- entities_in_resolution_groups: 9
- entity_count_after_safe_resolution: 389
- canonical_relationship_count: 394
- weak_edge_count: 117
- orphan_entities_with_weak_edges: 39
- original_relationship_count: 407
- changed_or_collapsed_relationships: 10

## 1. Safe Entity Resolution Groups

- 태종#14 <= ['태종', '방원', '이방원'] / ids=[14, 15, 26] / freq_sum=6 / degree_sum=13
- 노비문서#390 <= ['노비 문서', '노비문서'] / ids=[168, 390] / freq_sum=2 / degree_sum=2
- 세종 대왕#106 <= ['세종', '세종 대왕'] / ids=[19, 106] / freq_sum=3 / degree_sum=9
- 흥선 대원군#296 <= ['흥선 대원군', '흥선대원군'] / ids=[296, 384] / freq_sum=7 / degree_sum=17

## 2. Weak Edges For Orphans

- 조준 -> 태종 w=1.4 co=2 source_id=1 source_type=인물
- 조준 -> 정도전 w=1.0 co=1 source_id=1 source_type=인물
- 조준 -> 이성계 w=1.0 co=1 source_id=1 source_type=인물
- 류큐 -> 정도전 w=1.0 co=1 source_id=39 source_type=인물
- 류큐 -> 태종 w=1.0 co=1 source_id=39 source_type=인물
- 류큐 -> 태조 w=1.0 co=1 source_id=39 source_type=인물
- 시암(타이) -> 정도전 w=1.0 co=1 source_id=40 source_type=인물
- 시암(타이) -> 태종 w=1.0 co=1 source_id=40 source_type=인물
- 시암(타이) -> 태조 w=1.0 co=1 source_id=40 source_type=인물
- 자와(자바) -> 정도전 w=1.0 co=1 source_id=41 source_type=인물
- 자와(자바) -> 태종 w=1.0 co=1 source_id=41 source_type=인물
- 자와(자바) -> 태조 w=1.0 co=1 source_id=41 source_type=인물
- 승정원 -> 정도전 w=1.0 co=1 source_id=47 source_type=기관
- 승정원 -> 태종 w=1.0 co=1 source_id=47 source_type=기관
- 승정원 -> 태조 w=1.0 co=1 source_id=47 source_type=기관
- 춘추관 -> 정도전 w=1.0 co=1 source_id=49 source_type=기관
- 춘추관 -> 태종 w=1.0 co=1 source_id=49 source_type=기관
- 춘추관 -> 태조 w=1.0 co=1 source_id=49 source_type=기관
- 한성부 -> 정도전 w=1.0 co=1 source_id=51 source_type=기관
- 한성부 -> 태종 w=1.0 co=1 source_id=51 source_type=기관
- 한성부 -> 태조 w=1.0 co=1 source_id=51 source_type=기관
- 유향소(향청) -> 정도전 w=1.0 co=1 source_id=54 source_type=기관
- 유향소(향청) -> 태종 w=1.0 co=1 source_id=54 source_type=기관
- 유향소(향청) -> 태조 w=1.0 co=1 source_id=54 source_type=기관
- 잡과 -> 세종 대왕 w=1.0 co=1 source_id=65 source_type=정책
- 잡과 -> 성균관 w=1.0 co=1 source_id=65 source_type=정책
- 잡과 -> 신문고 w=1.0 co=1 source_id=65 source_type=정책
- 문음 -> 세종 대왕 w=1.0 co=1 source_id=66 source_type=정책
- 문음 -> 성균관 w=1.0 co=1 source_id=66 source_type=정책
- 문음 -> 신문고 w=1.0 co=1 source_id=66 source_type=정책
- 천거 -> 세종 대왕 w=1.0 co=1 source_id=67 source_type=정책
- 천거 -> 성균관 w=1.0 co=1 source_id=67 source_type=정책
- 천거 -> 신문고 w=1.0 co=1 source_id=67 source_type=정책
- 수군 -> 세종 대왕 w=1.0 co=1 source_id=72 source_type=기관
- 수군 -> 성균관 w=1.0 co=1 source_id=72 source_type=기관
- 수군 -> 신문고 w=1.0 co=1 source_id=72 source_type=기관
- 역졸 -> 세종 대왕 w=1.0 co=1 source_id=81 source_type=기관
- 역졸 -> 성균관 w=1.0 co=1 source_id=81 source_type=기관
- 역졸 -> 신문고 w=1.0 co=1 source_id=81 source_type=기관
- 봉수 제도 -> 세종 대왕 w=1.0 co=1 source_id=84 source_type=정책
- 봉수 제도 -> 성균관 w=1.0 co=1 source_id=84 source_type=정책
- 봉수 제도 -> 신문고 w=1.0 co=1 source_id=84 source_type=정책
- 국조오례의 -> 정도전 w=1.0 co=1 source_id=94 source_type=문물
- 국조오례의 -> 위화도 회군 w=1.0 co=1 source_id=94 source_type=문물
- 국조오례의 -> 조선 w=0.75 co=1 source_id=94 source_type=문물
- 삼강행실도 -> 정도전 w=1.0 co=1 source_id=95 source_type=문물
- 삼강행실도 -> 위화도 회군 w=1.0 co=1 source_id=95 source_type=문물
- 삼강행실도 -> 조선 w=0.75 co=1 source_id=95 source_type=문물
- 인지의 -> 정도전 w=1.0 co=1 source_id=102 source_type=문물
- 인지의 -> 위화도 회군 w=1.0 co=1 source_id=102 source_type=문물
- 인지의 -> 조선 w=0.75 co=1 source_id=102 source_type=문물
- 동문선 -> 정도전 w=1.0 co=1 source_id=103 source_type=문물
- 동문선 -> 위화도 회군 w=1.0 co=1 source_id=103 source_type=문물
- 동문선 -> 조선 w=0.75 co=1 source_id=103 source_type=문물
- 동인 -> 경국대전 w=1.0 co=1 source_id=120 source_type=기관
- 동인 -> 농사직설 w=1.0 co=1 source_id=120 source_type=기관
- 동인 -> 사림 w=0.75 co=1 source_id=120 source_type=기관
- 왜란 -> 태종 w=1.0 co=1 source_id=141 source_type=사건
- 왜란 -> 성종 w=1.0 co=1 source_id=141 source_type=사건
- 왜란 -> 유석진 w=1.0 co=1 source_id=141 source_type=사건
- 일본 도요토미 히데요시 -> 양반 w=1.0 co=1 source_id=174 source_type=인물
- 일본 도요토미 히데요시 -> 여진족 w=1.0 co=1 source_id=174 source_type=인물
- 일본 도요토미 히데요시 -> 조선 수군 w=1.0 co=1 source_id=174 source_type=인물
- 북인 -> 의정부 w=1.0 co=1 source_id=211 source_type=기관
- 북인 -> 홍문관 w=1.0 co=1 source_id=211 source_type=기관
- 북인 -> 사림 w=0.75 co=1 source_id=211 source_type=기관
- 소수 특정 가문 -> 성균관 w=1.0 co=1 source_id=217 source_type=기관
- 소수 특정 가문 -> 노비 w=1.0 co=1 source_id=217 source_type=기관
- 소수 특정 가문 -> 남인 w=1.0 co=1 source_id=217 source_type=기관
- 속오례의 -> 성균관 w=1.0 co=1 source_id=224 source_type=문물
- 속오례의 -> 노비 w=1.0 co=1 source_id=224 source_type=문물
- 속오례의 -> 남인 w=1.0 co=1 source_id=224 source_type=문물
- 동국문헌비고 -> 성균관 w=1.0 co=1 source_id=225 source_type=문물
- 동국문헌비고 -> 노비 w=1.0 co=1 source_id=225 source_type=문물
- 동국문헌비고 -> 남인 w=1.0 co=1 source_id=225 source_type=문물
- 동문휘고 -> 성균관 w=1.0 co=1 source_id=231 source_type=문물
- 동문휘고 -> 노비 w=1.0 co=1 source_id=231 source_type=문물
- 동문휘고 -> 남인 w=1.0 co=1 source_id=231 source_type=문물
- 탁지지 -> 성균관 w=1.0 co=1 source_id=232 source_type=문물
- 탁지지 -> 노비 w=1.0 co=1 source_id=232 source_type=문물
- 탁지지 -> 남인 w=1.0 co=1 source_id=232 source_type=문물
- 규장전운 -> 성균관 w=1.0 co=1 source_id=233 source_type=문물
- 규장전운 -> 노비 w=1.0 co=1 source_id=233 source_type=문물
- 규장전운 -> 남인 w=1.0 co=1 source_id=233 source_type=문물
- 부농 -> 남인 w=1.0 co=1 source_id=236 source_type=기관
- 부농 -> 노론 w=1.0 co=1 source_id=236 source_type=기관
- 부농 -> 붕당 정치 w=1.0 co=1 source_id=236 source_type=기관
- 이수광 -> 남인 w=1.0 co=1 source_id=238 source_type=인물
- 이수광 -> 노론 w=1.0 co=1 source_id=238 source_type=인물
- 이수광 -> 붕당 정치 w=1.0 co=1 source_id=238 source_type=인물
- 이제마 -> 허준 w=1.0 co=1 source_id=260 source_type=인물
- 이제마 -> 유수원 w=1.0 co=1 source_id=260 source_type=인물
- 이제마 -> 홍대용 w=1.0 co=1 source_id=260 source_type=인물
- 전세 -> 세도 정치 w=0.75 co=1 source_id=272 source_type=정책
- 전세 -> 순조 w=1.0 co=1 source_id=272 source_type=정책
- 전세 -> 헌종 w=1.0 co=1 source_id=272 source_type=정책
- 군포 -> 세도 정치 w=0.75 co=1 source_id=273 source_type=정책
- 군포 -> 순조 w=1.0 co=1 source_id=273 source_type=정책
- 군포 -> 헌종 w=1.0 co=1 source_id=273 source_type=정책
- 미륵불 신앙 -> 정조 w=1.0 co=1 source_id=285 source_type=문물
- 미륵불 신앙 -> 순조 w=1.0 co=1 source_id=285 source_type=문물
- 미륵불 신앙 -> 정감록 w=1.0 co=1 source_id=285 source_type=문물
- 연해주 -> 세도 정치 w=0.75 co=1 source_id=300 source_type=기관
- 연해주 -> 농민 봉기 w=1.0 co=1 source_id=300 source_type=기관
- 연해주 -> 천주교 w=1.0 co=1 source_id=300 source_type=기관
- 사창제 -> 서원 w=1.0 co=1 source_id=307 source_type=정책
- 사창제 -> 조선 정부 w=0.75 co=1 source_id=307 source_type=정책
- 사창제 -> 천주교 w=1.0 co=1 source_id=307 source_type=정책
- 수호 통상 조약 -> 조선 정부 w=0.75 co=1 source_id=331 source_type=사건
- 수호 통상 조약 -> 청 w=1.0 co=1 source_id=331 source_type=사건
- 수호 통상 조약 -> 흥선 대원군 w=0.75 co=1 source_id=331 source_type=사건
- 조선책략 -> 고종 w=1.0 co=1 source_id=345 source_type=정책
- 조선책략 -> 강화도 조약 w=1.0 co=1 source_id=345 source_type=정책
- 조선책략 -> 통리기무아문 w=1.0 co=1 source_id=345 source_type=정책
- 위정척사 -> 고종 w=1.0 co=1 source_id=346 source_type=정책
- 위정척사 -> 강화도 조약 w=1.0 co=1 source_id=346 source_type=정책
- 위정척사 -> 통리기무아문 w=1.0 co=1 source_id=346 source_type=정책

## 3. Notes

- safe entity resolution은 동일 정규화명 + 호환 타입인 경우만 자동 병합 후보로 잡았습니다.
- substring 유사 후보는 오탐 위험이 커서 자동 병합하지 않았습니다.
- orphan 보강은 같은 text_unit 공출현만 낮은 weight의 weak edge로 추가합니다.
- 이 결과를 실제 GraphRAG 원본에 반영하려면 별도 검증 후 canonical graph를 만들어야 합니다.