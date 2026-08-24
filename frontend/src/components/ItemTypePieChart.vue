<script setup>
import { computed, ref, watch } from 'vue'
import { buildPieSlices } from '@/utils/pieChart'

const props = defineProps({
  items: { type: Array, default: () => [] },
  maxSlices: { type: Number, default: 15 },
  grandTotal: { type: Number, default: 0 },
  batchTotal: { type: Number, default: 0 },
  centerLabel: { type: String, default: '不合格项次' },
  countUnit: { type: String, default: '次' },
})

const chartKey = ref(0)
watch(
  () => [props.items, props.maxSlices, props.grandTotal],
  () => {
    chartKey.value += 1
  },
  { deep: true },
)

const uid = `pie-${Math.random().toString(36).slice(2, 9)}`

const slices = computed(() =>
  buildPieSlices(props.items, {
    maxSlices: props.maxSlices,
    grandTotal: props.grandTotal,
    mergeOther: true,
  }),
)

const displayTotal = computed(() => {
  if (props.grandTotal > 0) return props.grandTotal
  return (props.items || []).reduce((sum, item) => sum + (item.count || 0), 0)
})

const activeIndex = ref(-1)

function sliceStyle(index) {
  return { '--slice-delay': `${index * 0.055}s` }
}

function sliceHoverTransform(slice) {
  const dist = 4.5
  const rad = ((slice.midAngle - 90) * Math.PI) / 180
  const tx = Math.cos(rad) * dist
  const ty = Math.sin(rad) * dist
  return `translate(${tx} ${ty}) scale(1.025)`
}
</script>

<template>
  <div v-if="slices.length" class="pie-layout">
    <div class="pie-wrap">
      <svg
        :key="chartKey"
        class="pie-svg"
        viewBox="0 0 200 200"
        role="img"
        :aria-label="`${centerLabel} ${displayTotal.toLocaleString()}`"
      >
        <defs>
          <filter :id="`${uid}-glow`" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient
            v-for="(slice, index) in slices"
            :id="`${uid}-grad-${index}`"
            :key="`${uid}-grad-${index}`"
            gradientUnits="userSpaceOnUse"
            :x1="100"
            :y1="20"
            :x2="100"
            :y2="180"
          >
            <stop offset="0%" :stop-color="slice.gradient[0]" stop-opacity="0.98" />
            <stop offset="42%" :stop-color="slice.gradient[1]" stop-opacity="0.82" />
            <stop offset="100%" :stop-color="slice.gradient[2]" stop-opacity="0.62" />
          </linearGradient>
        </defs>

        <circle class="pie-bg-ring" cx="100" cy="100" r="92" />

        <g class="pie-slices" :filter="`url(#${uid}-glow)`">
          <g
            v-for="(slice, index) in slices"
            :key="slice.name"
            class="pie-slice-group"
            :transform="activeIndex === index ? sliceHoverTransform(slice) : ''"
          >
            <path
              class="pie-slice"
              :class="{ 'pie-slice--active': activeIndex === index }"
              :d="slice.path"
              :fill="`url(#${uid}-grad-${index})`"
              :style="sliceStyle(index)"
              @mouseenter="activeIndex = index"
              @mouseleave="activeIndex = -1"
            />
          </g>
        </g>
      </svg>

      <div class="pie-hole">
        <span class="pie-hole__value">{{ displayTotal.toLocaleString() }}</span>
        <span class="pie-hole__label">{{ centerLabel }}</span>
        <span
          v-if="batchTotal > 0 && batchTotal !== displayTotal"
          class="pie-hole__sub"
        >{{ batchTotal.toLocaleString() }} 批次</span>
      </div>
    </div>

    <ul class="pie-legend">
      <li
        v-for="(slice, index) in slices"
        :key="slice.name"
        class="pie-legend__item"
        :class="{ 'pie-legend__item--active': activeIndex === index }"
        @mouseenter="activeIndex = index"
        @mouseleave="activeIndex = -1"
      >
        <div class="pie-legend__head">
          <span
            class="pie-legend__dot"
            :style="{
              background: `linear-gradient(135deg, ${slice.gradient[0]}, ${slice.gradient[1]})`,
              boxShadow: `0 2px 8px ${slice.gradient[1]}55`,
            }"
          />
          <span class="pie-legend__name" :title="slice.name">{{ slice.name }}</span>
          <span class="pie-legend__stats">
            <span class="pie-legend__count">{{ slice.count }} {{ countUnit }}</span>
            <span class="pie-legend__share">{{ slice.share }}%</span>
          </span>
        </div>
        <div class="pie-legend__bar">
          <div
            class="pie-legend__bar-fill"
            :style="{
              width: `${slice.share}%`,
              background: `linear-gradient(90deg, ${slice.gradient[0]}, ${slice.gradient[1]})`,
            }"
          />
        </div>
      </li>
    </ul>
  </div>
  <el-empty v-else description="暂无不合格项目数据" :image-size="80" />
</template>

<style scoped>
.pie-layout {
  display: grid;
  grid-template-columns: min(300px, 40%) minmax(0, 1fr);
  align-items: start;
  gap: 16px 20px;
  padding: 8px 4px 4px;
  min-width: 0;
}

.pie-wrap {
  position: relative;
  width: 100%;
  max-width: 300px;
  aspect-ratio: 1;
  height: auto;
  justify-self: center;
  filter: drop-shadow(0 12px 28px rgba(59, 100, 200, 0.14));
}

.pie-svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.pie-bg-ring {
  fill: none;
  stroke: rgba(255, 255, 255, 0.65);
  stroke-width: 1.5;
}

.pie-slices {
  transform-origin: 100px 100px;
}

.pie-slice {
  opacity: 0;
  transform-origin: 100px 100px;
  cursor: pointer;
  stroke: rgba(255, 255, 255, 0.45);
  stroke-width: 0.6;
  animation: pieSliceIn 0.9s cubic-bezier(0.22, 1, 0.36, 1) forwards;
  animation-delay: var(--slice-delay, 0s);
  transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s ease;
}

.pie-slice--active {
  opacity: 1 !important;
}

.pie-wrap::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: conic-gradient(
    from 210deg,
    transparent 0deg,
    rgba(255, 255, 255, 0.28) 28deg,
    transparent 56deg
  );
  pointer-events: none;
  mix-blend-mode: soft-light;
  animation: pieShine 10s linear infinite;
}

.pie-slice-group {
  transition: transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.pie-hole {
  position: absolute;
  inset: 16%;
  border-radius: 50%;
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 255, 0.88));
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 -8px 24px rgba(59, 100, 200, 0.06),
    0 4px 16px rgba(15, 23, 42, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.8);
  pointer-events: none;
}

.pie-hole__value {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
  animation: countFadeIn 0.6s ease 0.35s both;
}

.pie-hole__label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  animation: countFadeIn 0.6s ease 0.45s both;
}

.pie-hole__sub {
  font-size: 11px;
  color: #cbd5e1;
  margin-top: 2px;
}

.pie-legend {
  width: 100%;
  list-style: none;
  margin: 0;
  padding: 10px 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px 14px;
  max-height: 420px;
  overflow-y: auto;
  overflow-x: hidden;
  border-radius: var(--app-radius-sm);
  background: rgba(248, 250, 252, 0.55);
  border: 1px solid rgba(226, 232, 240, 0.65);
  align-content: start;
}

.pie-legend__item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 13px;
  padding: 6px 8px;
  border-radius: 8px;
  min-width: 0;
  transition: background 0.2s ease;
  cursor: default;
}

.pie-legend__head {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px 8px;
  min-width: 0;
  width: 100%;
}

.pie-legend__item--active {
  background: rgba(155, 192, 255, 0.14);
}

.pie-legend__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.7);
}

.pie-legend__name {
  color: #334155;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pie-legend__stats {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  white-space: nowrap;
  flex-shrink: 0;
}

.pie-legend__count {
  color: #64748b;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.pie-legend__share {
  color: #0f172a;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.pie-legend__bar {
  height: 4px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.95);
  overflow: hidden;
}

.pie-legend__bar-fill {
  height: 100%;
  border-radius: 999px;
  min-width: 2px;
  transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

@media (max-width: 900px) {
  .pie-layout {
    grid-template-columns: 1fr;
  }

  .pie-wrap {
    justify-self: center;
  }

  .pie-legend {
    grid-template-columns: 1fr;
  }
}

@keyframes pieSliceIn {
  0% {
    opacity: 0;
    transform: scale(0.86);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes countFadeIn {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes pieShine {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
