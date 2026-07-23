# 标准库 MySQL 备份目录
#
# 放置 `STSC_standard_database.sql.gz`（或任意 *.sql.gz / *.sql）。
# 首次启动时 `scripts/setup_mysql.py` 会自动导入到 MYSQL_DATABASE。
#
# 若 Git 克隆后此目录为空：
# 1. 安装 Git LFS 后重新拉取：git lfs pull
# 2. 或向维护人员索取备份，复制到本目录后重新运行 启动ZKBZ.bat
