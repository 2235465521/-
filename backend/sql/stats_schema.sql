-- 预统计汇总表（OLAP 层）：总览、地图、省市区列表从此读取，避免请求时扫百万行
USE shipin;

CREATE TABLE IF NOT EXISTS stats_global (
  id TINYINT NOT NULL PRIMARY KEY DEFAULT 1,
  qualified_count BIGINT NOT NULL DEFAULT 0 COMMENT '合格批次数',
  unqualified_row_count BIGINT NOT NULL DEFAULT 0 COMMENT '不合格批次数',
  unqualified_item_count BIGINT NOT NULL DEFAULT 0 COMMENT '不合格项次（与饼图口径一致）',
  total_files INT NOT NULL DEFAULT 0 COMMENT '有效数据文件数',
  refreshed_at DATETIME NOT NULL COMMENT '最近刷新时间',
  CONSTRAINT chk_stats_global_singleton CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='全局统计快照';

CREATE TABLE IF NOT EXISTS stats_region (
  province VARCHAR(50) NOT NULL COMMENT '省份',
  city VARCHAR(50) NOT NULL DEFAULT '' COMMENT '城市，空串表示省级汇总粒度之一',
  year VARCHAR(10) NOT NULL DEFAULT '' COMMENT '年份，空串表示年份未知',
  qualified_count BIGINT NOT NULL DEFAULT 0,
  unqualified_row_count BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (province, city, year),
  KEY idx_stats_region_province (province),
  KEY idx_stats_region_prov_year (province, year),
  KEY idx_stats_region_year (year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='按省/市/年聚合';

CREATE TABLE IF NOT EXISTS dim_region (
  province VARCHAR(50) NOT NULL,
  city VARCHAR(50) NOT NULL DEFAULT '',
  PRIMARY KEY (province, city),
  KEY idx_dim_region_province (province)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='省市区维度';

-- 榜单预聚合：按省/全国缓存单位榜与产品榜 JSON（city 空串表示省级/全国粒度）
CREATE TABLE IF NOT EXISTS stats_rank_cache (
  province VARCHAR(50) NOT NULL COMMENT '省份，全部为「全部」',
  city VARCHAR(50) NOT NULL DEFAULT '' COMMENT '城市，预聚合仅到省级（空串）',
  units_json MEDIUMTEXT NOT NULL COMMENT '单位红绿榜等',
  products_json MEDIUMTEXT NOT NULL COMMENT '产品榜单等',
  refreshed_at DATETIME NOT NULL COMMENT '最近刷新时间',
  PRIMARY KEY (province, city),
  KEY idx_stats_rank_refreshed (refreshed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='榜单预聚合缓存';
