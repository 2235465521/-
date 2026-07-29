# ZKBZ 标准 PDF 下载

从 GitHub 克隆后，**双击 `启动ZKBZ.bat` 即可**（会自动装依赖、导入标准库、启动服务）。

不想每次都在 Cursor 里手动启动时：

| 方式 | 说明 |
|------|------|
| 双击 **`打开ZKBZ.bat`** | 若服务未开则自动启动，并打开 http://127.0.0.1:5000/ |
| 运行 **`创建桌面快捷方式.bat`** | 在桌面生成「打开ZKBZ」图标，以后双击即可 |
| 运行 **`安装开机自启.bat`** | 登录 Windows 后自动打开平台（取消用 `取消开机自启.bat`） |

说明：浏览器访问网址**不能**单独唤醒未运行的程序；需先有本机服务在听 5000 端口。用上面的脚本即可不依赖 Cursor。

系统数据源为 **MySQL**。标准库备份已放在项目内 `data/db_dump/`。

## 一键运行（推荐）

### Windows

1. 安装 [Python 3](https://www.python.org/downloads/)（勾选 Add to PATH）  
2. 安装并启动 [MySQL](https://dev.mysql.com/downloads/mysql/)（或 Docker，见下）  
3. 若仓库使用 Git LFS 存备份：先 `git lfs install` 再 `git lfs pull`  
4. 双击 **`启动ZKBZ.bat`**

首次启动会：

- 生成 `.env`（若没有）  
- 检测 MySQL 连接  
- 若库为空，自动导入 `data/db_dump/*.sql.gz`（约数分钟）  
- 打开 http://127.0.0.1:5000/

页眉显示 **数据库: MySQL · 就绪** 即成功。系统**无需登录**，打开即可检索与下载。

### AI检索（开箱即用）

标准检索页自带「AI检索」，克隆启动后即可用自然语言查标准，**无需额外部署或自行申请 Key**。

项目内置默认智谱 Key（额度共享）。若要用自己的账号，在 `.env` 覆盖：

```env
ZHIPU_API_KEY=你的智谱Key
ZHIPU_MODEL=glm-4-flash
```

### 没有本机 MySQL 时用 Docker

```bat
docker compose up -d mysql
```

编辑 `.env`（或首次自动生成后修改）：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=zkbz
MYSQL_DATABASE=STSC_standard_database
```

再运行 `启动ZKBZ.bat`（会把项目内备份导入该 Docker MySQL）。

## 目录说明

| 路径 | 说明 |
|------|------|
| `frontend/` | **静态** HTML/CSS/JS，由 Flask 直接托管（**无** Vite，一般不必 `npm run build`） |
| `data/db_dump/*.sql.gz` | 标准库备份（大文件，建议 Git LFS） |
| `scripts/setup_mysql.py` | 启动前自动建库/导入 |
| `.env.example` | 配置模板 |
| `docker-compose.yml` | 可选 MySQL 容器 |

## 下载 PDF

检索只依赖 MySQL；下载实体文件还需在 `.env` 配置：

```env
PDF_ROOT=你的标准PDF根目录
```

## 常见问题

**在服务器执行 `cd frontend && npm run build` 报找不到 package.json？**  
本前端是静态页，本来可以没有 Node 工程。现已提供兼容的 `frontend/package.json`：再执行 `npm run build` 会空构建并同步到 `frontend/dist/`。  
**正确做法仍是**：在项目根目录启动 Flask（`启动ZKBZ.bat` / 等价命令），不要把本项目当成 Vue/Vite 站点单独 `npm run dev`。

**标准库未就绪**  
- MySQL 服务是否启动  
- `.env` 密码是否正确  
- `data/db_dump/` 是否有 `.sql.gz`（没有则 `git lfs pull`）  

**GitHub 拉不下备份**  
备份约 240MB+，需安装 [Git LFS](https://git-lfs.com/) 后执行 `git lfs pull`。

更多说明见 `使用文档.md`。
