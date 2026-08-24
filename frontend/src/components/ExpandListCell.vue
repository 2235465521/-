<script setup>
import { computed } from 'vue'
import { normalizeProductDisplayName } from '@/utils/format'

const props = defineProps({
  sections: { type: Array, default: null },
  values: { type: Array, default: () => [] },
  separator: { type: String, default: '、' },
  previewMax: { type: Number, default: 2 },
  align: { type: String, default: 'left' },
  emptyText: { type: String, default: '-' },
})

const normalizedSections = computed(() => {
  const normalizeValues = (values) =>
    [...new Set((values || []).map((v) => normalizeProductDisplayName(v)).filter(Boolean))]

  if (props.sections != null) {
    return props.sections
      .filter((section) => section?.values?.length)
      .map((section) => ({
        label: section.label || '',
        values: normalizeValues(Array.isArray(section.values) ? section.values : [section.values]),
      }))
      .filter((section) => section.values.length)
  }
  if (props.values?.length) return [{ label: '', values: normalizeValues(props.values) }]
  return []
})

const flatValues = computed(() => normalizedSections.value.flatMap((section) => section.values))

const isEmpty = computed(() => !flatValues.value.length)

const previewText = computed(() => {
  if (isEmpty.value) return props.emptyText
  const shown = flatValues.value.slice(0, props.previewMax).join(props.separator)
  if (flatValues.value.length > props.previewMax) return `${shown}${props.separator}…`
  return shown
})

const hasMore = computed(() => flatValues.value.length > props.previewMax)
</script>

<template>
  <span
    v-if="isEmpty"
    class="expand-list-cell expand-list-cell--empty"
    :class="`expand-list-cell--${align}`"
  >{{ emptyText }}</span>
  <el-tooltip
    v-else
    effect="light"
    :placement="align === 'right' ? 'bottom-end' : 'bottom-start'"
    :fallback-placements="['bottom-start', 'bottom-end', 'top-start', 'top-end']"
    :show-after="280"
    popper-class="expand-list-popover"
    :teleported="true"
    :class="['expand-list-cell-tooltip', align === 'right' ? 'expand-list-cell-tooltip--right' : '']"
  >
    <template #content>
      <div class="expand-list-popover__body">
        <section
          v-for="section in normalizedSections"
          :key="section.label || section.values.join('|')"
          class="expand-list-popover__section"
        >
          <header v-if="section.label" class="expand-list-popover__label">{{ section.label }}</header>
          <p class="expand-list-popover__text">{{ section.values.join(separator) }}</p>
        </section>
      </div>
    </template>
    <span
      class="expand-list-cell expand-list-cell__preview"
      :class="[
        `expand-list-cell--${align}`,
        { 'expand-list-cell--more': hasMore },
      ]"
    >
      {{ previewText }}
    </span>
  </el-tooltip>
</template>

<style scoped>
.expand-list-cell {
  line-height: 1.45;
  vertical-align: top;
}

.expand-list-cell-tooltip {
  display: block;
  max-width: 100%;
  vertical-align: top;
}

.expand-list-cell-tooltip--right {
  width: 100%;
  min-width: 0;
  margin-left: auto;
}

.expand-list-cell--left {
  display: inline-block;
  max-width: 100%;
  text-align: left;
}

.expand-list-cell--right {
  display: block;
  width: 100%;
  min-width: 0;
  text-align: right;
}

.expand-list-cell--empty.expand-list-cell--right {
  display: block;
  width: 100%;
  text-align: right;
}

.expand-list-cell--empty {
  color: var(--app-text-muted);
}

.expand-list-cell__preview {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
  min-width: 0;
}

.expand-list-cell--left.expand-list-cell__preview {
  display: inline-block;
  max-width: 100%;
}

.expand-list-cell--right.expand-list-cell__preview {
  display: block;
  width: 100%;
  text-align: right;
}

.expand-list-cell--more.expand-list-cell__preview {
  color: var(--app-text);
}
</style>
