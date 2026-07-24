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
- 打开 http://127.0.0.1:5000/login

页眉显示 **数据库: MySQL · 就绪** 即成功。

### AI 自然语言检索（可选）

在 `.env` 配置智谱 API Key 后，标准检索页可使用「AI检索」：

```env
ZHIPU_API_KEY=你的智谱Key
ZHIPU_MODEL=glm-4-flash
```

用口语描述需求（如「近五年现行饮料国标」），系统会解析为筛选条件并自动检索。

### 默认账号

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 普通用户 | `user` | `user123` |
| 管理员 | 由部署方自行创建/配置，不在登录页展示 | — |

- **普通用户**：检索、下载、批量打包；可进后台「个人中心」查看本人信息并修改密码  
- **管理员**：上述全部 + 后台「用户管理」（新建/改角色/停用/重置密码）  
- 自行注册：`.env` 中 `ALLOW_REGISTER=true`（默认开启），新注册账号均为普通用户

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
