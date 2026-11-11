-- ============================================================================
-- ngram FULLTEXT 召回方案（#4 的可选替代路径）
-- ----------------------------------------------------------------------------
-- 现状：search_query.extract_text_keywords 把中文短语拆成子词，再 OR 拼接
--       `std_chinesename LIKE '%kw%'`，每个关键词一次全表扫描（478k 行代价大）。
-- 目标：用 ngram 全文索引替代 LIKE，提升召回性能与稳定性。
--
-- 验证结论（本地 STSC_standard_database 副本，478,623 行，2026-11-11）：
--   查询           LIKE 命中   ngram FT 命中   关系
--   储能              645         645          完全一致（2 字词）
--   光伏             1473        1473          完全一致（2 字词）
--   储能电池           19        3871          超集（ngram 拆 储能/能电/电池 做 OR，召回更高、精度更低）
--   电动汽车          888        8777          超集（同上）
--   => 2 字词：ngram FT 与 LIKE 完全等价，且走索引免全表扫描；
--      长短语：ngram FT 为超集，召回更高但需 BOOLEAN MODE / 二次 LIKE 过滤控精度。
--   限制：ngram_token_size 默认 2，单字查询（<2 字）无法命中，需上层保证最小词长 2。
--   结论：纯代码 OR 展开已达成召回扩展目标；ngram 仅在超大表 LIKE 扫描代价过高时作为索引化可选方案。
-- ============================================================================

-- 1) 构建索引前，确认服务端 ngram_token_size（只读变量，需改配置重启才生效）。
--    SHOW VARIABLES LIKE 'ngram_token_size';   -- 默认 2，对中文最合适，一般无需改动。
--    若需单字召回，设为 1 并重启；但索引膨胀明显，通常不推荐。

-- 2) 构建 ngram 全文索引（InnoDB + utf8mb4 列可直接使用 ngram parser）：
ALTER TABLE std_base
  ADD FULLTEXT INDEX idx_ft_chinesename (std_chinesename)
  WITH PARSER ngram;

-- 3) 应用层改用 MATCH ... AGAINST 召回（IN NATURAL LANGUAGE MODE）：
--    SELECT ... FROM std_base
--    WHERE MATCH(std_chinesename) AGAINST (%s IN NATURAL LANGUAGE MODE);
--    注意：把原 extract_text_keywords 产出的多关键词 OR 逻辑，
--    改为「整词 + 子词」拼接成单串后一次性 MATCH，或用 BOOLEAN MODE 加 + 前缀。

-- 4) 回滚：
--    ALTER TABLE std_base DROP INDEX idx_ft_chinesename;

-- 说明：当前主线已采用「纯代码 OR 展开」方案（extract_text_keywords），
--       该方案无需改库、可直接上线。本脚本为可选增强，按需执行。
