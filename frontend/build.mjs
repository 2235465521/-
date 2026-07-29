/**
 * 兼容误用「cd frontend && npm run build」的部署脚本。
 * 本目录是静态资源，无 Vite/Webpack；构建为空操作并成功退出。
 */
import { mkdirSync, cpSync, existsSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const dist = join(root, "dist");

mkdirSync(dist, { recursive: true });
for (const name of ["index.html", "css", "js"]) {
  const src = join(root, name);
  if (!existsSync(src)) continue;
  cpSync(src, join(dist, name), { recursive: true });
}
writeFileSync(
  join(dist, ".zkbz-static"),
  "ZKBZ frontend is static; served by Flask from frontend/ (dist is a copy for npm pipelines).\n",
  "utf8"
);

console.log(
  "[zkbz] frontend 为静态页面，无需真实打包。已同步到 frontend/dist（若部署脚本需要 dist）。"
);
console.log("[zkbz] 正确启动：在项目根目录运行 Flask（启动ZKBZ.bat / python -m backend 等）。");
