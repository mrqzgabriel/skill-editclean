// EditClean - shot_page.cjs (v3.0) — prints REAIS de paginas com Playwright + Chrome do sistema.
// Chamado pelo shot_page.py. Modos:
//   full     rola a pagina inteira (revela conteudo que so aparece no scroll) e salva fullPage
//   figures  screenshot POR ELEMENTO de cada <figure>, <table>, <svg> grande, [role=img]
//            (coordenadas de fullPage deslocam em pagina longa; por elemento e exato)
//   element  screenshot do primeiro elemento que casa com --selector
// Opcoes: viewport WxH, dpr, aceitar cookies, zoom css (nao recomendado: extrapola a viewport)
const path = require("path");
const fs = require("fs");

const args = JSON.parse(process.argv[2]);
const pwDir = args.playwright_dir;
const { chromium } = require(path.join(pwDir, "node_modules", "playwright"));

(async () => {
  const browser = await chromium.launch({ channel: args.channel || "chrome", headless: true });
  const ctx = await browser.newContext({
    viewport: { width: args.width || 1440, height: args.height || 1000 },
    deviceScaleFactor: args.dpr || 2,
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    locale: args.locale || "pt-BR",
  });
  const page = await ctx.newPage();
  await page.goto(args.url, { waitUntil: "networkidle", timeout: 90000 });
  if (args.accept_cookies !== false) {
    for (const t of ["Accept all cookies", "Accept all", "Aceitar todos", "Aceitar", "Accept", "I agree", "Concordo"]) {
      const b = page.getByRole("button", { name: t });
      if (await b.count()) { await b.first().click().catch(() => {}); break; }
    }
  }
  await page.waitForTimeout(800);
  if (args.scroll !== false) {
    const total = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < total + 1000; y += args.scroll_step || 350) {
      await page.evaluate((v) => window.scrollTo(0, v), y);
      await page.waitForTimeout(args.scroll_wait || 100);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(800);
  }
  const out = { url: args.url, files: [] };
  fs.mkdirSync(args.outdir, { recursive: true });
  const stem = args.stem || "page";
  if (args.mode === "full") {
    const f = path.join(args.outdir, `${stem}_full.png`);
    await page.screenshot({ path: f, fullPage: true });
    out.files.push({ file: f, kind: "full" });
  } else if (args.mode === "element") {
    const loc = page.locator(args.selector).first();
    await loc.scrollIntoViewIfNeeded(); await page.waitForTimeout(600);
    const f = path.join(args.outdir, `${stem}_element.png`);
    await loc.screenshot({ path: f });
    const box = await loc.boundingBox();
    out.files.push({ file: f, kind: "element", selector: args.selector, box });
  } else {
    const sel = args.selector || "figure, table, [role=img], svg";
    const locs = page.locator(sel);
    const n = await locs.count();
    const minW = args.min_width || 300, minH = args.min_height || 120;
    for (let i = 0; i < n; i++) {
      const el = locs.nth(i);
      const box = await el.boundingBox().catch(() => null);
      if (!box || box.width < minW || box.height < minH) continue;
      // svg dentro de figure ja sai na figure
      const insideFigure = await el.evaluate((e) => !!e.closest("figure") && e.tagName.toLowerCase() !== "figure").catch(() => false);
      if (insideFigure) continue;
      await el.scrollIntoViewIfNeeded().catch(() => {}); await page.waitForTimeout(args.element_wait || 700);
      const txt = ((await el.innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 140);
      const f = path.join(args.outdir, `${stem}_fig${i}.png`);
      try { await el.screenshot({ path: f }); } catch (e) { continue; }
      out.files.push({ file: f, kind: "figure", index: i, width: Math.round(box.width), height: Math.round(box.height), text: txt });
    }
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.error("ERRO", e.message); process.exit(1); });
