export function displayReason(item) {
  const reason = (item.reason || '').trim()
  if (reason) return reason
  const itemName = (item.unqualified_item || '').trim()
  if (itemName) return `不合格项目：${itemName}`
  return '-'
}

export function formatSourceLocation(item) {
  const prov = item.source_province || ''
  const city = item.source_city || ''
  if (prov && city) return `${prov} / ${city}`
  return prov || city || '-'
}

export function formatMainReasons(reasons) {
  if (!reasons?.length) return '-'
  return reasons.map((r) => `${r.reason}（${r.ratio}%）`).join('、')
}

/** 常见标准不合格项目名（用于主干合并；与后端池逻辑一致） */
const FAILURE_ITEM_CANONICAL_POOL = [
  '阴离子合成洗涤剂',
  '大肠菌群',
  '菌落总数',
  '铜绿假单胞菌',
  '金黄色葡萄球菌',
  '二氧化硫残留量',
  '咪鲜胺和咪鲜胺锰盐',
  '氯氟氰菊酯和高效氯氟氰菊酯',
  '恩诺沙星',
  '吡虫啉',
  '噻虫胺',
  '吡唑醚菌酯',
  '联苯菊酯',
  '苯醚甲环唑',
  '腈苯唑',
  '黄曲霉毒素B₁',
  '脱氢乙酸及其钠盐',
  '柠檬黄',
  '诱惑红',
  '苋菜红',
  '胭脂红',
  '糖精钠',
  '亚硝酸盐',
  '溴酸盐',
  '酸价',
  '过氧化值',
  '铝的残留量',
  '孔雀石绿',
  '氧氟沙星',
  '金刚烷胺',
  '克伦特罗',
  '腐霉利',
  '氟苯尼考',
  '氯霉素',
  '甲硝唑',
  '4-氯苯氧乙酸钠',
]

const MEASUREMENT_BASIS_MAP = {
  铝: '铝的残留量',
  al: '铝的残留量',
  ai: '铝的残留量',
  a1: '铝的残留量',
  铅: '铅',
  pb: '铅',
  镉: '镉',
  cd: '镉',
  汞: '汞',
  hg: '汞',
  砷: '砷',
  as: '砷',
  脂肪: '酸价',
  山梨酸: '山梨酸',
}

function resolveMeasurementBasisFragment(text) {
  const compact = String(text || '').replace(/\s+/g, '').trim()
  if (!compact) return ''
  const only = compact.match(/^(?:样品)?以([A-Za-z\u4e00-\u9fa5]{1,16})计$/)
  if (only) {
    const basis = only[1]
    return MEASUREMENT_BASIS_MAP[basis] || MEASUREMENT_BASIS_MAP[basis.toLowerCase()] || compact
  }
  const suffix = compact.match(/^(.{1,24}?)以([A-Za-z\u4e00-\u9fa5]{1,16})计$/)
  if (suffix) {
    const itemPart = suffix[1]
    const basis = suffix[2]
    const mapped = MEASUREMENT_BASIS_MAP[basis] || MEASUREMENT_BASIS_MAP[basis.toLowerCase()]
    if (itemPart === '铅' || itemPart === '镉' || itemPart === '汞' || itemPart === '砷' || itemPart === '铝') {
      return mapped || itemPart
    }
    if (mapped && (itemPart === mapped || mapped.includes(itemPart))) return mapped
    if (mapped) return mapped
  }
  return compact
}

/** 将缩写/碎片并入同一主干的标准项目名 */
export function mergeFailureItemStem(compact, pool = FAILURE_ITEM_CANONICAL_POOL) {
  const text = String(compact || '').trim()
  if (!text || text === '其他' || text === '未标注') return text
  const prefixHits = pool.filter(
    (name) => name.startsWith(text) && name.length > text.length && text.length >= 3,
  )
  if (prefixHits.length) {
    return prefixHits.sort((a, b) => b.length - a.length)[0]
  }
  const suffixHits = pool.filter(
    (name) => name.endsWith(text) && name.length > text.length && text.length >= 2,
  )
  if (suffixHits.length) {
    if (suffixHits.length === 1) return suffixHits[0]
    if (text === '洗涤剂') {
      const detergent = suffixHits.filter((name) => name.includes('阴离子') || name.includes('合成洗涤'))
      if (detergent.length) return detergent.sort((a, b) => b.length - a.length)[0]
    }
    const shared = suffixHits[0].slice(0, 2)
    const grouped = suffixHits.filter((name) => name.startsWith(shared))
    if (grouped.length) return grouped.sort((a, b) => b.length - a.length)[0]
  }
  if (pool.includes(text)) return text
  return text
}

/** 去掉「项目实测值分别为」等检测说明尾巴 */
function stripFailureItemMeasurementNarrative(text) {
  let compact = String(text || '').replace(/\s+/g, '').trim()
  if (!compact) return ''
  for (const marker of [
    '项目实测值分别为',
    '项目实测值',
    '检验项目实测',
    '项目实测',
    '项目检出',
    '项目不符合',
  ]) {
    if (compact.includes(marker)) {
      const head = compact.split(marker, 1)[0]
      if (head.length >= 2) return head
    }
  }
  const stripped = compact.replace(/(?:检验)?项目(?:实测|检出)(?:值)?(?:分别为|为|超标)?.*$/, '').trim()
  return stripped || compact
}

/** 扇形图：仅「防腐剂混合使用时各自用量…」缩为「防腐剂」 */
export function collapsePreservativeForPie(name) {
  const text = normalizeFailureItemName(name)
  if (!text) return text
  if (/防腐剂混合使用/.test(text)) return '防腐剂'
  return text
}

/** 产品名展示：碗10/碗1 → 碗 */
export function normalizeProductDisplayName(name) {
  let text = String(name || '').replace(/\s+/g, '').trim()
  if (!text) return ''
  if (/^碗\d{1,2}$/.test(text)) return '碗'
  const m = text.match(/^(.+?)([1-9]\d{0,2})$/)
  if (m && ['碗', '碟', '盘', '杯', '筷', '勺'].includes(m[1])) return m[1]
  if (/^(?:密胺|陶瓷|不锈钢|仿瓷)?(?:大|小|饭|汤|菜|骨|面|白|餐|消毒|粉)?碗\d{0,2}$/.test(text)) {
    return '碗'
  }
  return text
}

/** OCR/表头残片中含大肠菌群相关字样时，统一为「大肠菌群」 */
export function normalizeFailureItemName(name) {
  let text = String(name || '').replace(/\s+/g, '').trim()
  if (!text) return ''
  text = text.replace(/（/g, '(').replace(/）/g, ')')
  text = text.replace(/\(以[^)()]{1,40}计\)/g, '').trim()
  text = text.split('(')[0].split('（')[0].trim()
  text = stripFailureItemMeasurementNarrative(text)
  text = text.replace(/项目(?:实测|检出|不符合).*$/, '').trim()
  if (/大肠(?:杆菌|菌群|埃希氏菌)/.test(text)) return '大肠菌群'
  if (/^计[\d.]/.test(text) && /(?:洗剂|涤剂|洗涤剂|磺酸|苯磺酸)/.test(text)) {
    return '阴离子合成洗涤剂'
  }
  if (/阴离子.{0,6}洗涤剂/.test(text)) return '阴离子合成洗涤剂'
  if (/阴离子.{0,8}(?:洗|涤)/.test(text)) return '阴离子合成洗涤剂'
  if (text.includes('阴离子') && text.includes('洗涤剂')) return '阴离子合成洗涤剂'
  if (text === '阴离子合成' || text === '阴离子合成剂' || text === '离子合成洗涤剂') {
    return '阴离子合成洗涤剂'
  }
  if (/^4-滴(?:和2|和 2|和|钠盐|钠盐.*)?$/.test(text) || /^2,4-滴(?:和2|钠盐)?$/.test(text)) {
    return '2,4-滴'
  }
  if (/^样品以(?:Al|AI|铝)计[)）]?$/i.test(text) || /^以(?:Al|AI|铝)计[)）]?$/i.test(text) || /铝的残留量/.test(text)) {
    return '铝的残留量'
  }
  if (/孔雀石绿/.test(text)) return '其他'
  if (text.includes('恩诺沙星') && /孔雀石/.test(text)) return '恩诺沙星'
  if (text === '复检结果' || text === '报告' || text.endsWith('报告')) return '其他'
  if (text === '氯苯氧乙酸钠') return '4-氯苯氧乙酸钠'
  for (const prefix of ['均是', '均为', '都是']) {
    if (text.startsWith(prefix) && text.length > prefix.length + 1) {
      text = text.slice(prefix.length)
    }
  }
  if (/[\u4e00-\u9fa5]/.test(text)) {
    text = text.replace(
      /(?:μg\/kg|mg\/kg|g\/100g|mg\/100cm²|\/50cm²|μg|µg|ug|mg|g\/kg|kg|g|ml|l|cfu)$/gi,
      '',
    )
  }
  const basisResolved = resolveMeasurementBasisFragment(text)
  if (basisResolved !== text) return basisResolved
  if (/^(?:样品)?以[A-Za-z\u4e00-\u9fa5]{1,16}计[)）]?$/i.test(text)) return '铝的残留量'
  return text
}

/** 表头/流程/单位/误填产品类碎片，不作为独立不合格项目展示 */
export function shouldMergeFailureItemToOther(name) {
  const text = String(name || '').replace(/\s+/g, '').trim()
  if (!text) return true
  if (text === '复检结果' || text === '报告' || text.endsWith('报告')) return true
  if (/孔雀石绿/.test(text)) return true
  if (/^(?:mg|kg|gkg|mgkg|g|ug|µg|μg)[)）]?$/i.test(text)) return true
  if (/\d+cm[²2]/i.test(text) || /^\/?\d+cm[²2]?$/i.test(text) || /^\d+$/.test(text)) return true
  if (/(?:菜|餐|瓷|密胺|骨|深|白|小|大|圆|方)(?:盘|碟|碗|筷|勺)/.test(text)) return true
  if (/^(?:酒精度|甲醇|总酸|固形物)$/.test(text)) return true
  if (/^(?:汤碗|餐碗|瓷碗|密胺碗|餐饮具|消毒餐具)$/.test(text)) return true
  if (/食品接触用|纸包装及容器/.test(text)) return true
  return false
}

function mergeUnlabeledIntoOther(items) {
  if (!items?.length) return []
  const batchNames = items
    .map((item) => {
      const raw = item.name || item.reason || ''
      const compact = String(raw).replace(/\s+/g, '').trim()
      return compact ? normalizeFailureItemName(compact) : ''
    })
    .filter(Boolean)
  const pool = [...new Set([...FAILURE_ITEM_CANONICAL_POOL, ...batchNames])].sort(
    (a, b) => b.length - a.length,
  )
  const merged = new Map()
  let otherCount = 0
  for (const item of items) {
    const rawName = item.name || item.reason || ''
    const count = item.count || 0
    if (!rawName || rawName === '未标注' || rawName === '其他') {
      otherCount += count
      continue
    }
    const compact = String(rawName).replace(/\s+/g, '').trim()
    if (shouldMergeFailureItemToOther(compact)) {
      otherCount += count
      continue
    }
    let name = collapsePreservativeForPie(compact)
    name = mergeFailureItemStem(name, pool)
    if (!name || name === '其他') {
      otherCount += count
      continue
    }
    merged.set(name, (merged.get(name) || 0) + count)
  }
  const kept = [...merged.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count, ratio: 0 }))
  if (otherCount > 0) {
    kept.push({ name: '其他', count: otherCount, ratio: 0 })
  }
  return kept
}

/** 机构/表头/单位/误填产品碎片，不应作为不合格项目展示 */
export function isOrgFailureItemName(name) {
  const text = String(name || '').trim()
  if (!text || text === '项目' || text === '未标注' || text === '其他') return true
  if (text.length <= 1) return true
  if (/^果[ⅠI1lⅡ2Ⅲ3Ⅳ4]*标准限值/.test(text)) return true
  if (/^(?:mg|kg|gkg|mgkg|g|ug|µg|μg)[)）]?$/i.test(text)) return true
  if (/\d+cm[²2]/i.test(text) || /^\/?\d+cm[²2]?$/i.test(text)) return true
  if (/(?:菜|餐|瓷|密胺|骨|深|白|小|大|圆|方)(?:盘|碟|碗|筷|勺)/.test(text)) return true
  if (/^(?:汤碗|餐碗|瓷碗|密胺碗|餐饮具|消毒餐具)$/.test(text)) return true
  if (/食品接触用|纸包装及容器/.test(text)) return true
  const orgMarkers = [
    '科学院', '研究所', '研究院', '有限公司', '有限责任公司', '认证集团',
    '海关', '华测', '谱尼', '广电计量', '检验检测', '检测中心', '测试中心',
    '质量监督', '研究所有限', '生物与医学', '生态环境与', '广州海',
  ]
  return orgMarkers.some((m) => text.includes(m))
}

function filterBreakdownItems(items) {
  return (items || []).filter((item) => !isOrgFailureItemName(item?.name))
}

/** 表格扇形图：item_breakdown / main_reasons / 旧版 items 名称列表 */
export function resolveBreakdownItems(row) {
  if (!row) return []
  if (row.item_breakdown?.length) {
    return filterBreakdownItems(mergeUnlabeledIntoOther(row.item_breakdown))
  }
  if (row.main_reasons?.length) {
    return filterBreakdownItems(
      mergeUnlabeledIntoOther(
        row.main_reasons.map((r) => ({ name: r.reason, count: r.count, ratio: r.ratio })),
      ),
    )
  }
  const legacy = row.items
  if (!Array.isArray(legacy) || !legacy.length) return []
  if (typeof legacy[0] === 'object' && legacy[0] !== null) {
    return filterBreakdownItems(mergeUnlabeledIntoOther(legacy))
  }
  const share = Math.round((100 / legacy.length) * 10) / 10
  return filterBreakdownItems(
    mergeUnlabeledIntoOther(legacy.map((name) => ({ name, count: 1, ratio: share }))),
  )
}

export function formatScopeLabel(province, city) {
  let label = province === '全部' ? '全国' : province
  if (city && city !== '全部') label += ` / ${city}`
  return label
}

export function buildDateQueryParams(dateRange) {
  if (!dateRange?.[0] || !dateRange?.[1]) return {}
  return { date_from: dateRange[0], date_to: dateRange[1] }
}

export function formatDateRangeLabel(dateRange) {
  if (!dateRange?.[0] || !dateRange?.[1]) return ''
  return `${dateRange[0]} 至 ${dateRange[1]}`
}

export function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

export function describePieSlice(cx, cy, r, startAngle, endAngle) {
  if (endAngle - startAngle >= 360) {
    return `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r} Z`
  }
  const start = polarToCartesian(cx, cy, r, endAngle)
  const end = polarToCartesian(cx, cy, r, startAngle)
  const largeArc = endAngle - startAngle > 180 ? 1 : 0
  return `M ${cx} ${cy} L ${end.x} ${end.y} A ${r} ${r} 0 ${largeArc} 1 ${start.x} ${start.y} Z`
}
