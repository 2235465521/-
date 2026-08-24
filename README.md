# 食品安全监督抽查数据统计

Web 应用，用于汇总、查询和分析食品安全抽检 Excel 数据。

支持两种运行方式：

- **Windows 开发模式**：`start.bat`，前后端分离（5173 + 8080）
- **Linux / 生产模式**：`start-prod.sh`，单端口上线（8080 同时提供页面和 API）

---

## 环境要求

| 组件 | 要求 |
|------|------|
| Python | 3.10+（推荐 conda 环境 `chouchafenxi` 或 `.venv`） |
| Node.js | 18+（开发模式或生产构建时需要） |
| 数据源 | Excel 目录可访问，默认路径见下方 |
| 可选 | Tesseract OCR（部分扫描/识别场景） |

默认数据目录（按系统自动选择，可用 `DATA_ROOT` 覆盖）：

| 系统 | 默认路径 |
|------|----------|
| Windows | `Z:\全国各省市食品安全监督抽查` |
| Linux | `/mnt/std_bk/全国各省市食品安全监督抽查` |

---

## 首次安装

在项目根目录 `chouchafenxi` 下执行：

### 1. Python 后端

```bat
python -m venv .venv
.\.venv\Scripts\pip install -r backend\requirements.txt
```

### 2. 前端依赖

```bat
cd frontend
npm install
cd ..
```

> 若已有 `data_cache.json`（约 284 MB），首次启动会直接加载缓存，无需重新扫描全部 Excel。

---

## 日常启动（推荐）

**双击运行项目根目录下的 `start.bat`。**

脚本会自动：

1. 关闭占用 **8080**（后端）、**5173**（前端）的旧进程  
2. 启动后端 Flask（`:8080`）  
3. 启动前端 Vite（`:5173`）  
4. 等待就绪后打开浏览器  

### 启动后请保持两个窗口不要关闭

| 窗口标题 | 作用 |
|----------|------|
| 食品安全统计-后端 | Flask API，关闭后页面无数据 |
| 食品安全统计-前端 | Vue 开发服务器 |

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端页面 | http://127.0.0.1:5173 |
| 后端 API | http://127.0.0.1:8080 |
| 健康检查 | http://127.0.0.1:8080/api/health |

### 启动耗时说明

| 阶段 | 大约时间 | 说明 |
|------|----------|------|
| 后端可读 API | ~5 秒 | 加载 `backend/data_cache.json` |
| 后台索引预计算 | ~15~20 秒 | 榜单、分析页在此之后秒开 |
| Z 盘新文件检查 | ~30 秒（后台） | 不阻塞页面，状态栏可见进度 |

**建议：** 启动后等后端窗口出现 `Running on http://127.0.0.1:8080`，再刷新浏览器；榜单类页面可再等约 15 秒。

---

## 手动启动

需要分别开两个终端。

**终端 1 — 后端（必须先启动）：**

```bat
cd /d f:\BaiduDownLoad\chouchafenxi\backend
..\.venv\Scripts\python.exe app.py
```

看到 `Running on http://127.0.0.1:8080` 后再启动前端。

**终端 2 — 前端：**

```bat
cd /d f:\BaiduDownLoad\chouchafenxi\frontend
npm run dev
```

浏览器访问终端里显示的地址（一般为 http://127.0.0.1:5173）。

---

## 数据从哪来

```
Z 盘 Excel 文件
    → 后端扫描解析（增量，只处理新文件）
    → 缓存 backend/data_cache.json
    → 启动时加载到内存
    → API 供前端展示
```

- 点击侧边栏 **「重新扫描数据」** 可手动触发增量扫描  
- 启动后会自动在后台检查 Z 盘是否有新文件  
- Z 盘不可用时，只能查看已有缓存，无法更新

---

## 常见问题

### 页面全部没数据 / 一直 loading

**原因：** 只启动了前端，后端未运行。

终端若出现：

```
Error: connect ECONNREFUSED 127.0.0.1:8080
```

说明后端 8080 没有服务。请用 `start.bat` 或手动启动后端，然后 **刷新浏览器**。

---

### 前端端口不是 5173

若 5173 被占用，Vite 会自动改用 5174、5175 等。请以前端终端显示的地址为准，或关闭多余的 `npm run dev` 窗口后重新运行 `start.bat`。

---

### 榜单 / 分析页第一次很慢

全国范围的 analytics 首次计算约需 10~15 秒。后端启动后会在后台预计算；若刚启动就打开榜单，请稍等或刷新一次。

---

### 状态栏显示「正在后台检查新文件」

正常现象。系统在后台遍历 Z 盘统计是否有未入库文件，不影响查看已有数据。

---

### 如何确认后端正常

浏览器或命令行访问：

```
http://127.0.0.1:8080/api/health
```

应返回 `{"ok": true, "service": "food-inspection-api"}`。

---

## 目录结构

```
chouchafenxi/
├── start.bat              # Windows 开发一键启动
├── deploy.env             # 服务器部署配置（自动加载）
├── start-prod.sh          # Linux 生产一键启动
├── deploy/
│   └── chouchafenxi.service  # systemd 服务示例
├── README.md              # 本文档
├── backend/
│   ├── app.py             # 后端入口（开发/生产）
│   ├── data_cache.json    # 解析结果缓存（核心数据）
│   ├── config.py          # 配置（数据路径、端口等）
│   ├── requirements.txt
│   └── food_inspection/   # 扫描、解析、API 逻辑
└── frontend/
    ├── .env.production    # 生产 API 配置（同端口）
    ├── package.json
    └── src/               # Vue 3 前端源码
```

---

## 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATA_ROOT` | 见上方表格 | Excel 数据源目录 |
| `CACHE_FILE` | `backend/data_cache.json` | 缓存文件路径 |
| `APP_HOST` | Win `127.0.0.1` / Linux `0.0.0.0` | 监听地址 |
| `APP_PORT` | `8080` | 服务端口 |
| `PRODUCTION` | 空 | `1` 启用 Gunicorn/Waitress |
| `SERVE_STATIC` | 空（生产模式自动开启） | `1` 托管前端 dist |
| `STATIC_DIR` | `frontend/dist` | 前端构建产物目录 |
| `CORS_ORIGINS` | 开发模式为 Vite 地址 | 生产同端口时无需设置 |
| `DISABLE_AUTO_SCAN` | 空 | 设为 `1` 可禁用启动后自动扫描 |

---

## Linux 生产部署（推荐上线方式）

生产模式：**构建前端静态文件 + Gunicorn 单端口服务**，浏览器只访问一个地址。

### 1. 安装依赖

```bash
conda activate chouchafenxi
pip install -r backend/requirements.txt

cd frontend && npm install && cd ..
```

### 2. 部署配置（已内置，一般不用改）

项目根目录 `deploy.env` 已写好服务器默认值：

```
DATA_ROOT=/mnt/std_bk/全国各省市食品安全监督抽查
APP_HOST=0.0.0.0
APP_PORT=8080
```

后端启动时会自动加载，**无需每次手动 export**。临时覆盖仍可用环境变量，例如 `APP_PORT=8090 ./start-prod.sh`。

### 3. 一键启动

```bash
./start-prod.sh
```

脚本会：

1. `npm run build` 构建前端到 `frontend/dist/`
2. 以 `PRODUCTION=1` 启动 Gunicorn（默认 `0.0.0.0:8080`）
3. 后端同时托管 `/api/*` 和前端页面

### 4. 访问

| 服务 | 地址 |
|------|------|
| 页面 + API | `http://服务器IP:8080` |
| 健康检查 | `http://服务器IP:8080/api/health` |

### 5. 端口冲突

服务器上可能已有其他项目占用 8080。**不要终止其他项目的进程。**

- 自动换端口：`./start-prod.sh`（8080 被占用时会尝试 8081、8082…）
- 手动指定：`APP_PORT=8090 ./start-prod.sh`

### 6. systemd 开机自启（可选）

```bash
sudo cp deploy/chouchafenxi.service /etc/systemd/system/
# 按实际路径修改 User、ExecStart
sudo systemctl daemon-reload
sudo systemctl enable --now chouchafenxi
```

### 生产环境变量

| 变量 | Linux 默认 | 说明 |
|------|------------|------|
| `PRODUCTION` | `1`（start-prod.sh 自动设置） | 使用 Gunicorn/Waitress |
| `SERVE_STATIC` | `1` | 托管 `frontend/dist/` |
| `DATA_ROOT` | `/mnt/std_bk/全国各省市食品安全监督抽查` | Excel 数据源 |
| `APP_HOST` | `0.0.0.0` | 监听所有网卡 |
| `APP_PORT` | `8080` | 服务端口 |
| `DISABLE_AUTO_SCAN` | 空 | 设为 `1` 可禁用自动扫描 |

### Linux 与 Windows 的差异

- **打开源文件**：仅 Windows 客户端支持，Linux 服务器会返回 501
- **Excel COM 解析**：仅 Windows，Linux 使用 openpyxl/xlrd 等替代方案
- **网络盘 I/O**：扫描大量 Excel 时比本地盘慢，属正常现象

---

## 停止服务

关闭「食品安全统计-后端」和「食品安全统计-前端」两个命令行窗口即可。

或在任务管理器中结束对应 `python.exe` / `node.exe` 进程。
