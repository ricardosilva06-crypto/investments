// Generates PWA icons and iOS splash screens from public/icons/icon.svg.
// Uses Playwright's Chromium to rasterise (dev-only; output is committed).
// Usage: node scripts/generate-icons.mjs   (needs `playwright` installed locally or globally via NODE_PATH)
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const svg = await readFile(path.join(root, "public/icons/icon.svg"), "utf8");
const BG = "#0d0f13";

const browser = await chromium.launch();
const page = await browser.newPage();

async function render(file, w, h, html) {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<html><body style="margin:0;width:${w}px;height:${h}px;overflow:hidden">${html}</body></html>`);
  await page.screenshot({ path: path.join(root, "public", file), omitBackground: false });
  console.log("wrote", file);
}

const icon = (size, pad = 0, bg = "transparent") =>
  `<div style="width:100%;height:100%;display:grid;place-items:center;background:${bg}"><div style="width:${size - pad * 2}px;height:${size - pad * 2}px">${svg.replace("<svg ", '<svg width="100%" height="100%" ')}</div></div>`;

await render("icons/icon-192.png", 192, 192, icon(192, 0, BG));
await render("icons/icon-512.png", 512, 512, icon(512, 0, BG));
await render("icons/maskable-512.png", 512, 512, icon(512, 72, BG)); // safe zone for Android masks
await render("icons/apple-touch-icon.png", 180, 180, icon(180, 0, BG));

const splashes = [
  [1320, 2868], [1290, 2796], [1206, 2622], [1179, 2556], [1170, 2532], [1284, 2778], [1125, 2436], [750, 1334],
];
for (const [w, h] of splashes) {
  const s = Math.round(w * 0.22);
  await render(
    `splash/splash-${w}x${h}.png`,
    w,
    h,
    `<div style="width:100%;height:100%;background:${BG};display:flex;flex-direction:column;align-items:center;justify-content:center;gap:${Math.round(s * 0.25)}px;font-family:-apple-system,system-ui,sans-serif">
       <div style="width:${s}px;height:${s}px">${svg.replace("<svg ", '<svg width="100%" height="100%" ')}</div>
       <div style="color:#e9ebf2;font-size:${Math.round(w * 0.055)}px;font-weight:700;letter-spacing:-0.02em">Investor Intelligence</div>
     </div>`,
  );
}
await browser.close();
