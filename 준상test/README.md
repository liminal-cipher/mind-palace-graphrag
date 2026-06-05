# 광화문 VWorld 기억궁전 데모

VWorld 3D 광화문 지도 위에 5개의 기억궁전 외관 파빌리온을 실제 위경도 기반으로 배치한 공유용 데모입니다.

현재 공유 범위는 외관 데모입니다. PDF 분석, Azure 연동, 실내 1인칭 방 렌더링은 포함하지 않았습니다.

## 실행 방법

```bash
npm install
npm run dev
```

기본 주소:

```text
http://127.0.0.1:8765/
```

다른 포트로 열고 싶으면:

```powershell
$env:PORT="8769"; npm run dev
```

## VWorld 키 설정

방법 1. `.env` 파일 사용

```bash
VWORLD_API_KEY=발급받은_VWorld_API_Key
```

방법 2. 브라우저 입력

처음 접속하면 VWorld API Key 입력 패널이 뜹니다. 입력한 키는 서버 파일에 저장되지 않고 해당 브라우저의 `localStorage`에만 저장됩니다.

공유할 때 실제 키를 코드나 문서에 넣지 마세요.

## 현재 구조

```text
memory-palace-vworld/
  server.mjs
  vworld_3d_map_live.html
  room-01-sejong-daero.html
  room-02-yi-sunsin.html
  room-03-sejong.html
  room-04-gwanghwamun.html
  room-05-gyeongbokgung.html
  tests/
  public/
  .env.example
  package.json
```

## 핵심 구현

- VWorld WebGL 3D 지도를 실제 광화문 배경으로 사용합니다.
- 파빌리온 5개는 `lon`, `lat`, `altitude`를 원천 데이터로 가집니다.
- VWorld 3D viewer가 준비되면 WGS84 좌표를 화면 좌표로 투영해 overlay 위치를 동기화합니다.
- VWorld 투영이 아직 준비되지 않은 순간에만 위경도 범위 기반 fallback 배치를 사용합니다.
- 현재/인접 파빌리온만 자세히 표시하고, 멀리 있는 파빌리온은 경량 표시 또는 숨김 처리합니다.
- 파빌리온 클릭 시 각 room HTML로 이동합니다.

## 공유 방법

1. `node_modules/`는 공유하지 않습니다.
2. 키를 함께 공유해야 하면 `.env`를 포함합니다. 키를 공유하지 않을 때는 `.env`를 빼고 `.env.example`만 보냅니다.
3. 아래 파일과 폴더를 보내면 됩니다.

```text
.env
.env.example
.gitignore
README.md
PROJECT_CHECKPOINTS.md
package.json
package-lock.json
server.mjs
vworld_3d_map_live.html
room-01-sejong-daero.html
room-02-yi-sunsin.html
room-03-sejong.html
room-04-gwanghwamun.html
room-05-gyeongbokgung.html
tests/
public/
```

받는 사람은 압축을 풀고 `npm install`, `npm run dev` 순서로 실행하면 됩니다.

## 점검

```bash
npm test
```

테스트는 다음을 확인합니다.

- 서버가 VWorld 외관 데모만 제공하는지
- Cesium/Google/Photorealistic Tiles 경로가 공유본에 남지 않았는지
- 파빌리온이 고정 화면 좌표가 아니라 실제 지리 좌표로 배치되는지
- 5개 room 페이지가 모두 연결되는지
- README에 키를 직접 넣지 않았는지

## 다음 작업

1. 발표 화면 기준으로 파빌리온 크기와 라벨 위치를 polish
2. `room-01`부터 하나의 실내 1인칭 방을 프로토타입으로 제작
3. 파빌리온 외관을 GLB 또는 경량 Three.js 모델로 교체할지 검토
4. 배포할 도메인을 VWorld 허용 URL에 등록
