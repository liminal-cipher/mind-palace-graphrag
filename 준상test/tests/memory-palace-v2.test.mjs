import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("server is a share-ready VWorld exterior demo", async () => {
  const server = await readFile(new URL("server.mjs", root), "utf8");

  assert.match(server, /vworld_3d_map_live\.html/);
  assert.match(server, /vworld-exterior-palace/);
  assert.match(server, /\/api\/client-config/);
  assert.doesNotMatch(server, /multer|openai|analyze-pdf|suggest-mapping|chat-mapping/);
  assert.doesNotMatch(server, /CESIUM_ION_TOKEN|cesiumIonToken|cesiumTokenConfigured/);
});

test("package keeps only the dependencies needed to share and run the demo", async () => {
  const pkg = JSON.parse(await readFile(new URL("package.json", root), "utf8"));

  assert.equal(pkg.scripts.dev, "node server.mjs");
  assert.equal(pkg.scripts.test, "node --test tests/*.test.mjs");
  assert.deepEqual(Object.keys(pkg.dependencies).sort(), ["dotenv", "express"]);
});

test("VWorld page maps pavilions by real geography, not fixed screen coordinates", async () => {
  const html = await readFile(new URL("vworld_3d_map_live.html", root), "utf8");

  assert.match(html, /광화문 기억궁전 외관 루트/);
  assert.match(html, /PALACE_BUILDINGS/);
  assert.match(html, /lon:\s*126\.97686/);
  assert.match(html, /lat:\s*37\.57072/);
  assert.match(html, /altitude:\s*34/);
  assert.match(html, /projectGeoToScreen/);
  assert.match(html, /syncBuildingPositions/);
  assert.match(html, /Cartesian3\.fromDegrees/);
  assert.match(html, /dataset\.lon/);
  assert.match(html, /geo-fallback/);
  assert.match(html, /facility_build/);
  assert.doesNotMatch(html, /screen:\s*\{/);
  assert.doesNotMatch(html, /CesiumIonAuthPlugin|TilesRenderer|Google Photorealistic 3D Tiles/);
});

test("five exterior room entry pages exist and return to the map", async () => {
  const pages = [
    ["room-01-sejong-daero.html", /1단계 세종대로 진입부/],
    ["room-02-yi-sunsin.html", /2단계 이순신 동상/],
    ["room-03-sejong.html", /3단계 세종대왕 동상/],
    ["room-04-gwanghwamun.html", /4단계 광화문 앞/],
    ["room-05-gyeongbokgung.html", /5단계 경복궁 방향/]
  ];

  for (const [page, title] of pages) {
    const html = await readFile(new URL(page, root), "utf8");
    assert.match(html, title);
    assert.match(html, /광화문 맵으로 돌아가기/);
    assert.match(html, /Exterior entry page|외관|실내 렌더링|실내를 렌더링하지 않고|외관 shell/);
  }
});

test("README explains the safe sharing path without embedding keys", async () => {
  const readme = await readFile(new URL("README.md", root), "utf8");

  assert.match(readme, /공유 방법/);
  assert.match(readme, /npm install/);
  assert.match(readme, /VWORLD_API_KEY/);
  assert.match(readme, /localStorage/);
  assert.doesNotMatch(readme, /58278910-86B1-357A-861F-B07103B3C78E/);
});
