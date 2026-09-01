#!/usr/bin/env node
/*
 * EditClean - cover_gemini.cjs  (v2.10)
 *
 * Helper do make_cover.py: chama o MESMO modelo e a MESMA montagem do thumbnail do
 * influencIA (artifacts/api-server/src/lib/gemini.ts generateThumbnail):
 *   gemini-3-pro-image no Vertex AI, location "global", generateContent com
 *   [foto de referencia, (logo), prompt], responseModalities IMAGE+TEXT.
 *
 * Usa as bibliotecas do proprio influencIA (@google/genai, pg) resolvidas a partir da
 * pasta do repositorio (derivada do caminho do .env), e a credencial de servico que o
 * sistema guarda em gcp_credentials (a ativa com menos falhas). A chave nunca vai
 * para disco nem para o stdout.
 *
 * uso: node cover_gemini.cjs --env <.env do influencIA> --ref <imagem> [--logo <png>]
 *                            --prompt <arquivo.txt> --out <png bruto> [--model gemini-3-pro-image]
 */
const fs = require("fs");
const path = require("path");
const { createRequire } = require("module");

function arg(name, def) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : def;
}

function loadEnv(file) {
  const env = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
  return env;
}

function repoRootFromEnv(envPath) {
  return path.dirname(path.resolve(envPath));
}

function resolveFrom(root, name) {
  const candidates = [
    path.join(root, "artifacts", "api-server"),
    path.join(root, "lib", "db"),
    root,
  ];
  for (const c of candidates) {
    try {
      const req = createRequire(path.join(c, "package.json"));
      return req.resolve(name);
    } catch (_) { /* tenta o proximo */ }
  }
  throw new Error(`nao achei o modulo ${name} no repositorio do influencIA (${root})`);
}

function mimeOf(file) {
  const ext = path.extname(file).toLowerCase();
  return ext === ".png" ? "image/png" : ext === ".webp" ? "image/webp" : "image/jpeg";
}

(async () => {
  const envPath = arg("env");
  const ref = arg("ref");
  const logo = arg("logo", null);
  const promptFile = arg("prompt");
  const out = arg("out");
  const model = arg("model", "gemini-3-pro-image");
  if (!envPath || !ref || !promptFile || !out) {
    console.error("uso: --env .env --ref img --prompt txt --out png [--logo png] [--model ...]");
    process.exit(2);
  }
  const env = loadEnv(envPath);
  const root = repoRootFromEnv(envPath);

  // 1. credencial de servico do sistema (mesma tabela que o gcp-credential-manager le)
  const { Client } = require(resolveFrom(root, "pg"));
  const db = new Client({ connectionString: env.DATABASE_URL });
  await db.connect();
  const { rows } = await db.query(
    "select id,label,project_id,service_account_json from gcp_credentials where is_active order by fail_count asc, last_used_at desc nulls last limit 1");
  await db.end();
  if (!rows.length) throw new Error("nenhuma credencial GCP ativa em gcp_credentials");
  const cred = rows[0];
  const credentials = JSON.parse(cred.service_account_json);
  console.error(`[cover] credencial "${cred.label}" (projeto ${cred.project_id}), modelo ${model}`);

  // 2. cliente igual ao getGcpClientForLocation("global")
  const genaiPath = resolveFrom(root, "@google/genai");
  const { GoogleGenAI } = await import(genaiPath);
  const client = new GoogleGenAI({
    vertexai: true, project: cred.project_id, location: "global",
    googleAuthOptions: { credentials },
  });

  // 3. partes: referencia, (logo), prompt -- mesma ordem do generateThumbnail
  const parts = [{ inlineData: { data: fs.readFileSync(ref).toString("base64"), mimeType: mimeOf(ref) } }];
  if (logo) parts.push({ inlineData: { data: fs.readFileSync(logo).toString("base64"), mimeType: mimeOf(logo) } });
  parts.push({ text: fs.readFileSync(promptFile, "utf8") });

  const t0 = Date.now();
  const response = await client.models.generateContent({
    model,
    contents: [{ role: "user", parts }],
    config: { responseModalities: ["IMAGE", "TEXT"] },
  });
  const rparts = response.candidates?.[0]?.content?.parts || [];
  const img = rparts.find((p) => p.inlineData?.data);
  const txt = rparts.find((p) => p.text);
  if (!img) {
    throw new Error(`Gemini nao devolveu imagem (${txt ? String(txt.text).slice(0, 300) : "sem texto"})`);
  }
  fs.writeFileSync(out, Buffer.from(img.inlineData.data, "base64"));
  console.error(`[cover] imagem recebida em ${((Date.now() - t0) / 1000).toFixed(1)}s (${img.inlineData.mimeType || "?"})` +
    (txt ? ` | texto: ${String(txt.text).slice(0, 120).replace(/\n/g, " ")}` : ""));
  process.stdout.write(out + "\n");
})().catch((e) => {
  console.error("[cover] ERRO:", e && e.message ? e.message : e);
  process.exit(1);
});
