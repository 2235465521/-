"""MySQL 食品大类表达式：与 analytics._resolve_record_category 对齐。"""

from food_inspection.category_junk import MYSQL_CATEGORY_JUNK_REGEXP
_SRC = (
    "REPLACE(CONCAT("
    "COALESCE(food_name,''), COALESCE(unqualified_item,''), "
    "COALESCE(unqualified_reason,''), COALESCE(file_source,'')"
    "), ' ', '')"
)

_CAT = "TRIM(COALESCE(category, ''))"

# 表内别名 → 标准大类
_ALIAS_CASE = """
    WHEN {_cat} = '食用农产 品' THEN '食用农产品'
    WHEN {_cat} = '食用农产' THEN '食用农产品'
    WHEN {_cat} = '食用农 产品' THEN '食用农产品'
    WHEN {_cat} = '市 食用农产品' THEN '食用农产品'
    WHEN {_cat} = '粮食加工 品' THEN '粮食加工品'
    WHEN {_cat} = '茶叶及相 关制品' THEN '茶叶及相关制品'
    WHEN {_cat} = '茶叶及相' THEN '茶叶及相关制品'
    WHEN {_cat} = '食品添加 剂' THEN '食品添加剂'
    WHEN {_cat} = '可可及焙 烤咖啡产 品' THEN '可可及焙烤咖啡产品'
    WHEN {_cat} = '烤咖啡产' THEN '可可及焙烤咖啡产品'
    WHEN {_cat} = '品' THEN '未分类'
    WHEN {_cat} = '月饼' THEN '糕点'
    WHEN {_cat} = '水果类（必检）' THEN '食用农产品'
    WHEN {_cat} = '水果类（普通食品）' THEN '食用农产品'
    WHEN {_cat} = '蔬菜（必检）' THEN '食用农产品'
    WHEN {_cat} = '速冻面米制品' THEN '速冻食品'
    WHEN {_cat} = '速冻调制食品' THEN '速冻食品'
    WHEN {_cat} = '淀粉' THEN '淀粉及淀粉制品'
    WHEN {_cat} = '特殊膳食' THEN '特殊膳食食品'
    WHEN {_cat} = '婴幼儿配方食品' THEN '特殊膳食食品'
""".format(
    _cat=_CAT
)

_BAD_CAT = (
    f"{_CAT} REGEXP '{MYSQL_CATEGORY_JUNK_REGEXP}' "
    f"OR {_CAT} REGEXP '20[0-9]{{2}}[-/.]' "
    f"OR {_CAT} REGEXP '^20[0-9]{{6}}$' "
    f"OR {_CAT} REGEXP '^20[0-9]{{2}}' OR CHAR_LENGTH({_CAT}) > 24 "
    f"OR {_CAT} LIKE '%mg/%' OR {_CAT} LIKE '%mg/kg%' OR {_CAT} LIKE '%║%'"
)

# 从 category 列快速归一（库内已批量修正后使用；脏值归入未分类）
MYSQL_CATEGORY_ALIAS_EXPR = f"""
CASE
    {_ALIAS_CASE}
    WHEN {_BAD_CAT} THEN '未分类'
    WHEN {_CAT} IN ('', '未分类') OR {_CAT} IS NULL THEN '未分类'
    ELSE {_CAT}
END
""".strip()

# 从产品/路径文本推断大类（按优先级）
_INFER_CASE = f"""
    WHEN {_SRC} REGEXP '阴离子合成洗涤剂|合成洗涤剂|餐饮具|密胺|陶瓷|不锈钢|仿瓷|Melamine|餐盘|骨碟|汤碗|饭碗|菜盘|方盘|圆盘|长条盘|面碗|凉菜盘|小菜碗|大圆盘|米饭碗|菜碗|玻璃杯|水杯|料碗|蘸料碟|寿司盘|水果盘|豆浆碗|小吃盘|小圆盘|方形盘'
        THEN '餐饮具'
    WHEN {_SRC} REGEXP '塑料编织袋|淋膜纸|一次性纸碗|纸碗|品尝杯|食品包装|包装材料|复合膜|保鲜膜|塑料袋|塑料杯|纸杯|刀叉|吸管'
        THEN '食品包装材料'
    WHEN {_SRC} REGEXP '胶囊|口服液|片剂|软糖|压片糖果|维生素|鱼油|钙片|锌片|硒片|蛋白粉|氨糖|辅酶|褪黑素|益生菌|磷脂|胶原蛋白|氨基酸|甘草片|常菁茶|胖大海|保健'
        THEN '保健食品'
    WHEN {_SRC} REGEXP '花生油|菜籽油|葵花籽油|玉米油|橄榄油|大豆油|调和油|芝麻油|香油|猪油|牛油|羊油|油脂|煎炸过程用油|麻油|香麻油'
        THEN '食用油、油脂及其制品'
    WHEN {_SRC} REGEXP '香蕉|芒果|荔枝|龙眼|草莓|樱桃|葡萄|苹果|梨|橙|橘|柚|柠檬|西瓜|哈密瓜|番茄|西红柿|土豆|马铃薯|山药|生姜|韭菜|芹菜|菠菜|生菜|萝卜|胡萝卜|莲藕|丝瓜|冬瓜|南瓜|黄瓜|茄子|辣椒|蘑菇|香菇|木耳|豆芽|豆角|豇豆|鲜鸡|活鸡|排骨|猪蹄|鸡翅|鸡爪|牛腩|羊肉卷|鲜蛋|鸡蛋|鸭蛋|牛蛙|鲜玉米|花生米|农产品|农贸|流通环节'
        THEN '食用农产品'
    WHEN {_SRC} REGEXP '鱼片|鱼块|虾仁|蟹肉|贝类|螺肉|鱿鱼|带鱼|花甲|蛏子|鲍鱼|海参|海带|紫菜|基围虾|小龙虾|鲈鱼|黄鳍|黑鱼'
        THEN '水产制品'
    WHEN {_SRC} REGEXP '馒头|包子|油条|烧卖|烧麦|盒饭|煎饼|手抓饼|热干面|米粉|河粉|凉皮|肉夹馍|水饺|馄饨|汤圆|元宵|豆浆|豆腐脑|小作坊|餐饮|快餐|熟制|现制'
        THEN '餐饮食品'
    WHEN {_SRC} REGEXP '大米|面粉|小麦|挂面|面条|粉丝|粉条|方便面|年糕|糍粑'
        THEN '粮食加工品'
    WHEN {_SRC} REGEXP '酱油|食醋|蚝油|料酒|味精|鸡精|火锅底料|豆瓣|腐乳|辣酱|调味|花椒|八角|桂皮|孜然|胡椒'
        THEN '调味品'
    WHEN {_SRC} REGEXP '蛋糕|面包|月饼|酥饼|曲奇|蛋挞|糕点|桃酥|沙琪玛|麻花|糖果|巧克力'
        THEN '糕点'
    WHEN {_SRC} REGEXP '矿泉水|饮用水|果汁|汽水|可乐|茶饮|奶茶|咖啡|啤酒|白酒|葡萄酒|黄酒|功能饮料|乳饮料|豆奶|椰汁|劲酒|配制酒|露酒'
        THEN '饮料'
    WHEN {_SRC} REGEXP '牛奶|酸奶|奶酪|芝士|奶粉|炼乳|黄油|奶油|乳清'
        THEN '乳制品'
    WHEN {_SRC} REGEXP '火腿|香肠|腊肉|腊肠|酱肉|酱卤|肉松|肉干|肉脯|扒鸡|烧鸡|烤鸭|酱鸭'
        THEN '肉制品'
    WHEN {_SRC} REGEXP '豆腐|豆干|豆皮|腐竹|素鸡|千张|百叶'
        THEN '豆制品'
    WHEN {_SRC} REGEXP '薯片|虾条|膨化|锅巴|米花|仙贝'
        THEN '薯类和膨化食品'
    WHEN {_SRC} REGEXP '坚果|瓜子|炒花生|炒核桃|腰果|开心果|巴旦木|夏威夷果|碧根果|松子|榛子|杏仁'
        THEN '炒货食品及坚果制品'
    WHEN {_SRC} REGEXP '蜜饯|果脯|果干|话梅|山楂片|山楂糕|枣糕|芒果干|葡萄干'
        THEN '水果制品'
    WHEN {_SRC} REGEXP '酱菜|泡菜|酸菜|榨菜|萝卜干|脱水|干制|蔬菜干'
        THEN '蔬菜制品'
    WHEN {_SRC} REGEXP '速冻|冷冻饮品|冰淇淋|雪糕'
        THEN '速冻食品'
    WHEN {_SRC} REGEXP '饼干|威化|苏打饼'
        THEN '饼干'
    WHEN {_SRC} REGEXP '茶叶|绿茶|红茶|乌龙茶|普洱|白茶'
        THEN '茶叶及相关制品'
    WHEN {_SRC} REGEXP '淀粉|粉丝|粉条|凉粉'
        THEN '淀粉及淀粉制品'
"""

_PLACEHOLDER = (
    "'', '/', '-', '—', '无', '暂无', '不详', '未知', 'nan', 'none', 'null', "
    "'其他', '其他食品', '非食品', '未分类'"
)

_PREFER_INFER = "'食品相关产品', '工业加工食品', '餐饮加工食品', '其他食品'"

MYSQL_CATEGORY_EXPR = f"""
CASE
    {_ALIAS_CASE}
    WHEN {_BAD_CAT} THEN
        CASE
            {_INFER_CASE}
            ELSE '未分类'
        END
    WHEN {_CAT} IN ({_PREFER_INFER}) THEN
        CASE
            {_INFER_CASE}
            ELSE '餐饮具'
        END
    WHEN {_CAT} IN ({_PLACEHOLDER}) OR {_CAT} IS NULL THEN
        CASE
            {_INFER_CASE}
            ELSE '未分类'
        END
    WHEN {_CAT} <> '' THEN {_CAT}
    ELSE '未分类'
END
""".strip()
