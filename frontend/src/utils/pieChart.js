/** 晶莹剔透渐变配色：每段 [高光, 主色, 阴影] */
export const CRYSTAL_GRADIENTS = [
  ['#DCE9FF', '#9BC0FF', '#6B9AE8'],
  ['#C4FAF0', '#7EE8D8', '#4EC4B4'],
  ['#FFF0C4', '#FFD98A', '#E8B84A'],
  ['#E8DCFF', '#C4A8F0', '#9B7AD4'],
  ['#FFD8E4', '#FFA8BC', '#E87890'],
  ['#C8ECFF', '#8AD4FF', '#5AB0E8'],
  ['#D4F5C8', '#A8E090', '#78C068'],
  ['#D8E0FF', '#A8B8FF', '#7888E0'],
  ['#FFF4B8', '#FFE070', '#D8B040'],
  ['#ECD8FF', '#D0B0F8', '#A880E0'],
  ['#C8F4FF', '#90E0F8', '#58B8D8'],
  ['#E8ECF4', '#C8D0E0', '#98A4B8'],
]

export const OTHER_SLICE_NAMES = new Set(['其他', '其他分类', '未分类'])

export function polar(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return {
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  }
}

export function donutSlicePath(cx, cy, rOuter, rInner, startAngle, endAngle) {
  if (endAngle - startAngle >= 359.99) {
    endAngle = startAngle + 359.99
  }
  const largeArc = endAngle - startAngle > 180 ? 1 : 0
  const outerStart = polar(cx, cy, rOuter, startAngle)
  const outerEnd = polar(cx, cy, rOuter, endAngle)
  const innerEnd = polar(cx, cy, rInner, endAngle)
  const innerStart = polar(cx, cy, rInner, startAngle)
  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    'Z',
  ].join(' ')
}

/**
 * @param {Array<{name?: string, count?: number}>} items
 * @param {{ maxSlices?: number, grandTotal?: number, mergeOther?: boolean }} opts
 */
export function buildPieSlices(items, opts = {}) {
  const {
    maxSlices = 15,
    grandTotal = 0,
    mergeOther = true,
  } = opts

  const raw = [...(items || [])].sort((a, b) => (b.count || 0) - (a.count || 0))
  if (!raw.length) return []

  let grouped = raw
  if (mergeOther) {
    const named = raw.filter((item) => !OTHER_SLICE_NAMES.has(item.name))
    const otherFromApi = raw
      .filter((item) => OTHER_SLICE_NAMES.has(item.name))
      .reduce((sum, item) => sum + (item.count || 0), 0)
    const head = named.slice(0, maxSlices)
    const tail = named.slice(maxSlices)
    grouped = [...head]
    const tailCount = tail.reduce((sum, item) => sum + (item.count || 0), 0) + otherFromApi
    if (tailCount > 0) {
      grouped.push({ name: '其他', count: tailCount, ratio: 0 })
    }
  } else {
    grouped = raw.slice(0, maxSlices)
    const tail = raw.slice(maxSlices)
    if (tail.length) {
      grouped.push({
        name: '其他',
        count: tail.reduce((sum, item) => sum + (item.count || 0), 0),
      })
    }
  }

  const baseTotal = grandTotal || grouped.reduce((sum, item) => sum + (item.count || 0), 0) || 1
  let angle = 0
  const cx = 100
  const cy = 100
  const rOuter = 94
  const rInner = 46

  return grouped.map((item, index) => {
    const share = ((item.count || 0) / baseTotal) * 100
    const sweep = (share / 100) * 360
    const startAngle = angle
    const endAngle = angle + sweep
    angle = endAngle
    const midAngle = startAngle + sweep / 2
    const gradient = CRYSTAL_GRADIENTS[index % CRYSTAL_GRADIENTS.length]
    return {
      ...item,
      share: Math.round(share * 100) / 100,
      start: (startAngle / 360) * 100,
      end: (endAngle / 360) * 100,
      path: donutSlicePath(cx, cy, rOuter, rInner, startAngle, endAngle),
      midAngle,
      gradient,
      color: gradient[1],
    }
  })
}
