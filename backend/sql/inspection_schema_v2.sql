-- 食品安全抽检数据 — 五表结构 v2
-- 1. inspection_base      抽检基础信息（编号、省市、年份、结论、批次序号）
-- 2. inspection_company   被抽查单位 / 生产单位
-- 3. inspection_qualified 合格食品
-- 4. inspection_unqualified 不合格食品（含检测值、标准值）
-- 5. inspection_address   被抽查单位地址与行政区划

USE shipin1;

DROP TABLE IF EXISTS inspection_unqualified;
DROP TABLE IF EXISTS inspection_qualified;
DROP TABLE IF EXISTS inspection_company;
DROP TABLE IF EXISTS inspection_address;
DROP TABLE IF EXISTS inspection_base;

CREATE TABLE inspection_base (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '编号（从1递增）',
  province VARCHAR(50) NOT NULL COMMENT '抽查省份',
  city VARCHAR(50) NOT NULL DEFAULT '' COMMENT '抽查城市',
  year VARCHAR(10) NOT NULL DEFAULT '' COMMENT '抽查年份',
  status VARCHAR(10) NOT NULL COMMENT '合格 / 不合格',
  batch_serial VARCHAR(50) NOT NULL DEFAULT '' COMMENT '本批次抽查序号',
  file_source VARCHAR(512) NOT NULL DEFAULT '' COMMENT '源文件相对路径（溯源）',
  source_sheet VARCHAR(100) NOT NULL DEFAULT '' COMMENT 'Excel工作表名',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_base_scope (province, city, year),
  KEY idx_base_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='抽检基础表';

CREATE TABLE inspection_company (
  base_id BIGINT NOT NULL COMMENT '基础表编号',
  sampled_company VARCHAR(255) NOT NULL DEFAULT '' COMMENT '被抽查单位',
  manufacturer VARCHAR(255) NOT NULL DEFAULT '' COMMENT '生产/标称企业',
  PRIMARY KEY (base_id),
  CONSTRAINT fk_company_base FOREIGN KEY (base_id) REFERENCES inspection_base (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='抽检单位表';

CREATE TABLE inspection_qualified (
  base_id BIGINT NOT NULL COMMENT '基础表编号',
  result_label VARCHAR(10) NOT NULL DEFAULT '合格' COMMENT '检验结论',
  food_name VARCHAR(255) NOT NULL DEFAULT '' COMMENT '食品原名',
  category VARCHAR(100) NOT NULL DEFAULT '' COMMENT '食品大类',
  sub_category VARCHAR(128) NOT NULL DEFAULT '' COMMENT '食品小类',
  PRIMARY KEY (base_id),
  KEY idx_q_food (food_name),
  KEY idx_q_sub_category (sub_category),
  CONSTRAINT fk_qualified_base FOREIGN KEY (base_id) REFERENCES inspection_base (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='合格食品表';

CREATE TABLE inspection_unqualified (
  base_id BIGINT NOT NULL COMMENT '基础表编号',
  result_label VARCHAR(10) NOT NULL DEFAULT '不合格' COMMENT '检验结论',
  food_name VARCHAR(255) NOT NULL DEFAULT '' COMMENT '食品原名',
  category VARCHAR(100) NOT NULL DEFAULT '' COMMENT '食品大类',
  sub_category VARCHAR(128) NOT NULL DEFAULT '' COMMENT '食品小类',
  unqualified_item VARCHAR(255) NOT NULL DEFAULT '' COMMENT '不合格项目',
  test_result VARCHAR(255) NOT NULL DEFAULT '' COMMENT '检测结果（实测值）',
  standard_value VARCHAR(255) NOT NULL DEFAULT '' COMMENT '标准值',
  PRIMARY KEY (base_id),
  KEY idx_u_food (food_name),
  KEY idx_u_item (unqualified_item),
  KEY idx_u_sub_category (sub_category),
  CONSTRAINT fk_unqualified_base FOREIGN KEY (base_id) REFERENCES inspection_base (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='不合格食品表';

CREATE TABLE inspection_address (
  base_id BIGINT NOT NULL COMMENT '基础表编号',
  address TEXT COMMENT '被抽查单位地址',
  manufacturer_address TEXT COMMENT '生产企业地址',
  region VARCHAR(200) NOT NULL DEFAULT '' COMMENT '省市区/省市县',
  PRIMARY KEY (base_id),
  KEY idx_addr_region (region),
  CONSTRAINT fk_address_base FOREIGN KEY (base_id) REFERENCES inspection_base (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='被抽查单位地址表';

-- 兼容旧后端的只读视图（字段名与 food_inspection_records 一致）
DROP VIEW IF EXISTS food_inspection_records;
CREATE VIEW food_inspection_records AS
SELECT
  b.id AS id,
  CASE b.status WHEN '合格' THEN 'qualified' WHEN '不合格' THEN 'unqualified' ELSE b.status END AS status,
  b.province AS province,
  b.city AS city,
  CASE
    WHEN a.region <> '' AND a.region NOT LIKE CONCAT(b.province, '%')
      THEN SUBSTRING(a.region, CHAR_LENGTH(b.province) + 1)
    ELSE ''
  END AS county,
  b.year AS year,
  b.file_source AS file_source,
  b.source_sheet AS source_sheet,
  b.batch_serial AS serial_number,
  c.manufacturer AS manufacturer_name,
  a.manufacturer_address AS manufacturer_address,
  c.sampled_company AS sampled_company_name,
  a.address AS sampled_company_address,
  COALESCE(q.food_name, u.food_name) AS food_name,
  '/' AS specification,
  '/' AS trademark,
  NULL AS production_date_raw,
  CONCAT(
    COALESCE(u.unqualified_item, ''),
    CASE
      WHEN u.standard_value <> '' OR u.test_result <> ''
        THEN CONCAT('；标准: ', u.standard_value, '；实测: ', u.test_result)
      ELSE ''
    END
  ) AS unqualified_project_details,
  COALESCE(u.unqualified_item, '') AS unqualified_item,
  CASE
    WHEN u.standard_value <> '' OR u.test_result <> ''
      THEN CONCAT('标准: ', u.standard_value, '；实测: ', u.test_result)
    ELSE ''
  END AS unqualified_reason,
  COALESCE(q.category, u.category) AS category,
  COALESCE(q.sub_category, u.sub_category) AS sub_category,
  '' AS remarks,
  b.created_at AS created_at
FROM inspection_base b
LEFT JOIN inspection_company c ON c.base_id = b.id
LEFT JOIN inspection_address a ON a.base_id = b.id
LEFT JOIN inspection_qualified q ON q.base_id = b.id
LEFT JOIN inspection_unqualified u ON u.base_id = b.id;
