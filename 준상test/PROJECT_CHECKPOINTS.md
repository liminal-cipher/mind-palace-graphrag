# 광화문 VWorld 기억궁전 체크포인트

## 현재 공유 버전

목표는 VWorld 3D 광화문 지도 위에 5개의 기억궁전 외관 파빌리온을 실제 지리 좌표 기반으로 배치한 시연 데모입니다.

이번 공유본은 발표/피드백용 최소 구성입니다.

- 포함: VWorld 3D 지도, 지리 기반 파빌리온 overlay, 5개 room 입장 페이지
- 제외: PDF 업로드, Azure 분석, Cesium/Google 실사 타일 실험, 실내 1인칭 방 렌더링
- 실행: `npm install` 후 `npm run dev`
- 기본 주소: `http://127.0.0.1:8765/`

## 구현 완료

- [x] 서버 루트(`/`)를 `vworld_3d_map_live.html`로 고정
- [x] Cesium/Google/Photorealistic Tiles 경로를 공유 서버에서 제거
- [x] VWorld API key는 `.env` 또는 브라우저 `localStorage` 방식으로만 처리
- [x] 5개 파빌리온을 실제 `lon`, `lat`, `altitude` 데이터로 관리
- [x] VWorld 3D viewer의 WGS84 화면 투영값으로 overlay 위치 동기화
- [x] VWorld 투영 준비 전에는 위경도 범위 기반 fallback만 사용
- [x] 현재/인접 파빌리온은 상세 표시, 먼 파빌리온은 경량 표시 또는 숨김 처리
- [x] 파빌리온 클릭 시 개별 HTML 페이지로 이동
- [x] 공유용 README 정리
- [x] 불필요한 레거시 파일 제거 기준 수립

## 현재 파일 역할

| 파일 | 역할 |
| --- | --- |
| `server.mjs` | 로컬 Express 서버와 VWorld key 전달 |
| `vworld_3d_map_live.html` | 메인 VWorld 3D 기억궁전 화면 |
| `room-01-sejong-daero.html` | 1단계 입장 페이지 |
| `room-02-yi-sunsin.html` | 2단계 입장 페이지 |
| `room-03-sejong.html` | 3단계 입장 페이지 |
| `room-04-gwanghwamun.html` | 4단계 입장 페이지 |
| `room-05-gyeongbokgung.html` | 5단계 입장 페이지 |
| `tests/memory-palace-v2.test.mjs` | 공유본 회귀 테스트 |
| `public/vworld-geo-mapped-pavilions.png` | 최신 검증 스크린샷 |

## 공유 전 확인

1. 키를 함께 공유할 때만 `.env` 파일을 포함한다. 외부 공개 저장소에는 올리지 않는다.
2. `node_modules/`를 포함하지 않는다.
3. 실제 VWorld API key를 README나 HTML에 적지 않는다.
4. 공유받는 사람에게 `npm install`, `npm run dev` 순서를 안내한다.
5. VWorld 도메인 제한이 있으면 실행할 주소를 허용 URL에 등록한다.

## 다음 추천 작업

1. 발표 해상도 기준으로 파빌리온 크기와 라벨 위치 polish
2. `room-01`만 먼저 실제 실내 기억 방으로 확장
3. 외관 파빌리온을 GLB 또는 경량 Three.js 모델로 교체할지 검토
4. 배포 도메인을 정한 뒤 VWorld 허용 URL 정리
