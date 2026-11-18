// Screenshot workflows and executions in the THROWAWAY demo n8n (headless Chromium, loopback only).
// Usage: N8N_USER=.. N8N_PASS=.. NODE_PATH=<dir with playwright-core> node demo/n8n_shot.js jobs.json
//   jobs.json: {"base": "http://127.0.0.1:5711", "jobs": [{"url": "/workflow/<id>", "out": "x.png", "mode": "canvas"}]}
// Light theme on purpose: n8n's dark node bodies are dimmer than its dot grid and read badly.
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const BASE_DIR = path.join(process.env.HOME, ".cache/ms-playwright");

/** Path of the newest full Chromium build Playwright has installed (or CHROME_PATH). */
function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const dir = fs.readdirSync(BASE_DIR).filter(d => d.startsWith("chromium-") && !d.includes("headless")).sort().pop();
  const root = path.join(BASE_DIR, dir);
  const sub = fs.existsSync(path.join(root, "chrome-linux64")) ? "chrome-linux64" : "chrome-linux";
  return path.join(root, sub, "chrome");
}

/** Sign in with the throwaway owner from the environment. */
async function signIn(page, base) {
  await page.goto(`${base}/signin`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.setItem("N8N_THEME", "light"));
  await page.fill('input[type="email"], input[name="emailOrLdapLoginId"], input[name="email"]', process.env.N8N_USER);
  await page.fill('input[type="password"]', process.env.N8N_PASS);
  await page.keyboard.press("Enter");
  await page.waitForURL(u => !String(u).includes("/signin"), { timeout: 20000 });
}

// Hides only floating chrome (assistant bubble, toasts, banners); node issue badges are not hidden.
const CLEAN_CSS = `
  [data-test-id="ask-assistant-floating-button"], .el-notification, [class*="banner"], [data-test-id="banners"]
  { display: none !important; }
  .vue-flow__node .node-label, .vue-flow__node [class*="label"] { font-size: 15px !important; }`;

/** Bounding box around every canvas node plus padding, or null. */
async function nodesBox(frame, pad) {
  return frame.evaluate(p => {
    const r = [...document.querySelectorAll(".vue-flow__node")].map(e => e.getBoundingClientRect());
    if (!r.length) return null;
    const x0 = Math.max(0, Math.min(...r.map(b => b.left)) - p), y0 = Math.max(0, Math.min(...r.map(b => b.top)) - p);
    return { x: x0, y: y0, width: Math.max(...r.map(b => b.right)) + p - x0, height: Math.max(...r.map(b => b.bottom)) + p * 1.6 - y0 };
  }, pad);
}

/** One job: canvas = nodes only, zoomed to fit; execution = the whole executions view. */
async function shoot(page, base, job) {
  await page.goto(`${base}${job.url}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(job.mode === "canvas" ? ".vue-flow__node" : "iframe, .vue-flow__node", { timeout: 30000 });
  await page.addStyleTag({ content: CLEAN_CSS });
  await page.waitForTimeout(2500);
  if (job.mode === "canvas") {
    await page.mouse.move(800, 500);
    await page.keyboard.press("1");
    await page.mouse.move(1, 1);
    await page.waitForTimeout(1500);
    const box = await nodesBox(page, 50);
    await page.screenshot({ path: job.out, clip: box || undefined });
  } else {
    await page.screenshot({ path: job.out });
  }
  console.log(JSON.stringify({ url: job.url, out: job.out, ok: true }));
}

(async () => {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const browser = await chromium.launch({ executablePath: chromePath(), args: ["--no-sandbox", "--disable-dev-shm-usage"] });
  const page = await browser.newPage({ viewport: { width: 1680, height: 900 }, deviceScaleFactor: 2 });
  try {
    await signIn(page, spec.base);
    for (const job of spec.jobs) {
      try { await shoot(page, spec.base, job); }
      catch (e) { console.log(JSON.stringify({ url: job.url, ok: false, error: String(e).slice(0, 200) })); }
    }
  } finally { await browser.close(); }
})();
