<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  current: { type: Number, default: 1 },
  page: { type: Number, default: undefined },
  pageSize: { type: Number, required: true },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  showSizeChanger: { type: Boolean, default: true },
  pageSizeOptions: { type: Array, default: () => [50, 100, 200] },
  footerItemLabel: { type: String, default: '条记录' },
})

const emit = defineEmits(['page-change'])

const jumpPage = ref('')

const activePage = computed(() => props.page ?? props.current)

const totalPages = computed(() => Math.ceil(props.total / props.pageSize) || 1)

watch(activePage, () => {
  jumpPage.value = ''
})

const canFirst = computed(() => activePage.value > 1 && !props.loading)
const canPrev = computed(() => activePage.value > 1 && !props.loading)
const canNext = computed(() => activePage.value < totalPages.value && !props.loading)
const canLast = computed(() => activePage.value < totalPages.value && !props.loading)

function handlePageChange(page, pageSize = props.pageSize) {
  emit('page-change', page, pageSize)
}

function goFirst() {
  if (!canFirst.value) return
  handlePageChange(1, props.pageSize)
}

function goPrev() {
  if (!canPrev.value) return
  handlePageChange(activePage.value - 1, props.pageSize)
}

function goNext() {
  if (!canNext.value) return
  handlePageChange(activePage.value + 1, props.pageSize)
}

function goLast() {
  if (!canLast.value) return
  handlePageChange(totalPages.value, props.pageSize)
}

function onSizeChange(event) {
  handlePageChange(1, Number(event.target.value))
}

function onJumpInput(event) {
  jumpPage.value = event.target.value.replace(/\D/g, '')
}

function handleJump() {
  const target = parseInt(jumpPage.value, 10)
  if (Number.isNaN(target) || target < 1 || target > totalPages.value) {
    ElMessage.warning(`请输入 1 到 ${totalPages.value} 之间的有效页码`)
    return
  }
  handlePageChange(target, props.pageSize)
  jumpPage.value = ''
}
</script>

<template>
  <div class="page-table-footer">
    <div class="page-table-footer-meta">
      <div class="page-table-footer-total">
        共 <span class="page-table-footer-total-num">{{ total.toLocaleString() }}</span> {{ footerItemLabel }}
      </div>
      <label v-if="showSizeChanger" class="page-table-footer-size">
        每页
        <select
          class="page-table-footer-select"
          :value="pageSize"
          @change="onSizeChange"
        >
          <option v-for="size in pageSizeOptions" :key="size" :value="size">
            {{ size }}
          </option>
        </select>
        条
      </label>
    </div>

    <div class="page-table-footer-pills">
      <div class="page-pager-pill page-pager-pill--nav">
        <button
          type="button"
          class="page-pager-icon"
          :disabled="!canFirst"
          aria-label="首页"
          @click="goFirst"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
            <path d="M11 6l-6 6 6 6M18 6l-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <span class="page-pager-divider" aria-hidden="true" />
        <button
          type="button"
          class="page-pager-icon"
          :disabled="!canPrev"
          aria-label="上一页"
          @click="goPrev"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
            <path d="M15 6l-6 6 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>

        <div class="page-pager-indicator">
          <span class="page-pager-current">{{ activePage }}</span>
          <span class="page-pager-slash">/</span>
          <span class="page-pager-total">{{ totalPages }}</span>
        </div>

        <button
          type="button"
          class="page-pager-icon"
          :disabled="!canNext"
          aria-label="下一页"
          @click="goNext"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
            <path d="M9 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <span class="page-pager-divider" aria-hidden="true" />
        <button
          type="button"
          class="page-pager-icon"
          :disabled="!canLast"
          aria-label="末页"
          @click="goLast"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" aria-hidden="true">
            <path d="M6 6l6 6-6 6M13 6l6 6-6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>

      <div class="page-pager-pill page-pager-pill--jump">
        <span class="page-pager-jump-label">跳转</span>
        <input
          type="text"
          inputmode="numeric"
          class="page-pager-jump-input"
          :value="jumpPage"
          placeholder="页码"
          @input="onJumpInput"
          @keydown.enter="handleJump"
        />
        <span class="page-pager-jump-label">页</span>
        <button type="button" class="page-pager-confirm" @click="handleJump">
          确定
        </button>
      </div>
    </div>
  </div>
</template>
