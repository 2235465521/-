# ZKBZ 标准 PDF 下载

从 GitHub 克隆后，**双击 `启动ZKBZ.bat` 即可**（会自动装依赖、导入标准库、启动服务）。

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

页眉显示 **数据库: MySQL · 就绪** 即成功。

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

**标准库未就绪**  
- MySQL 服务是否启动  
- `.env` 密码是否正确  
- `data/db_dump/` 是否有 `.sql.gz`（没有则 `git lfs pull`）  

**GitHub 拉不下备份**  
备份约 240MB+，需安装 [Git LFS](https://git-lfs.com/) 后执行 `git lfs pull`。

更多说明见 `使用文档.md`。
