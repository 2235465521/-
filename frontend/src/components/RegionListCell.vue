<script setup>
import { computed } from 'vue'

const props = defineProps({
  provinces: { type: Array, default: () => [] },
  perColumn: { type: Number, default: 5 },
  emptyText: { type: String, default: '-' },
})

const provinceList = computed(() => (props.provinces || []).filter(Boolean))
const isEmpty = computed(() => !provinceList.value.length)

const provinceColumns = computed(() => toColumns(provinceList.value, props.perColumn))

function toColumns(items, perColumn) {
  if (!items.length) return []
  const cols = []
  for (let i = 0; i < items.length; i += perColumn) {
    cols.push(items.slice(i, i + perColumn))
  }
  return cols
}
</script>

<template>
  <span v-if="isEmpty" class="region-empty">{{ emptyText }}</span>
  <div v-else class="region-grid">
    <div class="region-col">
      <div v-if="provinceColumns.length" class="region-list-cols">
        <ul v-for="(col, idx) in provinceColumns" :key="`p-col-${idx}`" class="region-list">
          <li v-for="name in col" :key="`p-${name}`" class="region-item">
            <span class="region-dot region-dot--province" />
            <span class="region-name">{{ name }}</span>
          </li>
        </ul>
      </div>
      <span v-else class="region-empty-inline">{{ emptyText }}</span>
    </div>
  </div>
</template>

<style scoped>
.region-grid {
  display: block;
  padding: 2px 0;
  min-width: 0;
}

.region-col {
  min-width: 0;
  padding: 4px 6px;
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.55);
  border: 1px solid rgba(226, 232, 240, 0.55);
}

.region-col__label {
  font-size: 10px;
  font-weight: 600;
  color: var(--app-text-muted);
  letter-spacing: 0.04em;
  margin-bottom: 4px;
  padding-bottom: 3px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.6);
}

.region-list-cols {
  display: flex;
  align-items: flex-start;
  gap: 4px 8px;
  min-width: 0;
}

.region-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1 1 0;
  min-width: 0;
}

.region-item {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 1.35;
  min-width: 0;
  padding: 2px 0;
}

.region-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.75);
}

.region-dot--province {
  background: linear-gradient(135deg, #dce9ff, #9bc0ff);
}

.region-name {
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.region-empty,
.region-empty-inline {
  color: var(--app-text-muted);
  font-size: 12px;
}

.region-empty-inline {
  padding: 2px 0;
}
</style>
