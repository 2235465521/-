import { computed, inject } from 'vue'
import { buildDateQueryParams } from '@/utils/format'

export function useFilterScope() {
  const filters = inject('filters')
  const dateQuery = computed(() => buildDateQueryParams(filters.dateRange))
  return { filters, dateQuery }
}
