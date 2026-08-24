-- 食品原名 → 大类/小类 映射维表 + 业务表小类列

USE shipin;

CREATE TABLE IF NOT EXISTS dim_food_category_map (
  food_name_original VARCHAR(255) NOT NULL COMMENT '食品原名（与 inspection 表 food_name 精确匹配）',
  category_major VARCHAR(100) NOT NULL DEFAULT '' COMMENT '大类',
  category_minor VARCHAR(128) NOT NULL DEFAULT '' COMMENT '小类',
  standard_name VARCHAR(128) NOT NULL DEFAULT '' COMMENT '标准品名（备查）',
  map_source VARCHAR(32) NOT NULL DEFAULT '' COMMENT '分类来源',
  confidence VARCHAR(16) NOT NULL DEFAULT '' COMMENT '置信度',
  record_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '映射表记录数（参考）',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (food_name_original),
  KEY idx_food_map_major (category_major),
  KEY idx_food_map_minor (category_minor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='食品原名分类映射';

-- 业务表增加小类列（若已存在则跳过）
SET @db = DATABASE();

SET @sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'inspection_qualified' AND COLUMN_NAME = 'sub_category') = 0,
  'ALTER TABLE inspection_qualified ADD COLUMN sub_category VARCHAR(128) NOT NULL DEFAULT '''' COMMENT ''食品小类'' AFTER category',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = @db AND TABLE_NAME = 'inspection_unqualified' AND COLUMN_NAME = 'sub_category') = 0,
  'ALTER TABLE inspection_unqualified ADD COLUMN sub_category VARCHAR(128) NOT NULL DEFAULT '''' COMMENT ''食品小类'' AFTER category',
  'SELECT 1'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
