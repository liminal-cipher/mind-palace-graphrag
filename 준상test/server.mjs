import "dotenv/config";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PORT = Number(process.env.PORT || 8765);
const entryFile = path.join(__dirname, "vworld_3d_map_live.html");

const app = express();

app.use(express.json({ limit: "256kb" }));

app.get("/api/health", (_req, res) => {
  res.json({
    ok: true,
    app: "memory-palace-vworld",
    mode: "vworld-exterior-palace",
    vworldKeyConfigured: Boolean(process.env.VWORLD_API_KEY)
  });
});

app.get("/api/client-config", (_req, res) => {
  res.json({
    vworldApiKey: process.env.VWORLD_API_KEY || ""
  });
});

app.get("/", (_req, res) => {
  res.sendFile(entryFile);
});

app.use(express.static(__dirname, {
  extensions: ["html"],
  setHeaders(res) {
    res.setHeader("Cross-Origin-Opener-Policy", "same-origin-allow-popups");
  }
}));

app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(500).json({
    error: error.message || "서버 오류가 발생했습니다."
  });
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Memory Palace dev server: http://127.0.0.1:${PORT}`);
});
