<script setup>
import { useRoute } from 'vue-router'
import {
  DataAnalysis,
  CircleCheck,
  WarningFilled,
  TrendCharts,
  PieChart,
  Refresh,
  Download,
  Fold,
  Expand,
} from '@element-plus/icons-vue'

const props = defineProps({
  scanning: Boolean,
  exporting: Boolean,
  collapsed: { type: Boolean, default: false },
})

const emit = defineEmits(['scan', 'export', 'toggle'])

const route = useRoute()

const navItems = [
  { path: '/overview', title: '数据总览', desc: '合格 / 不合格 / 覆盖', icon: DataAnalysis },
  { path: '/qualified', title: '合格汇总', desc: '批次明细 · 筛选导出', icon: CircleCheck },
  { path: '/unqualified', title: '不合格汇总', desc: '项目明细 · 原因分析', icon: WarningFilled },
  { path: '/rank-product', title: '产品榜单', desc: '产品 · 项目 · 高频违规', icon: TrendCharts },
  { path: '/rank-unit', title: '单位红绿榜', desc: '被抽检/生产单位 · 红榜绿榜', icon: PieChart },
]

function isListRoute() {
  return route.name === 'qualified' || route.name === 'unqualified'
}

function isNavActive(item) {
  if (item.path === '/rank-product') {
    return route.path === '/rank-product' || route.path === '/distribution'
  }
  if (item.path === '/rank-unit') {
    return ['/rank-unit', '/rank-unit/failures', '/rank', '/alert', '/greenlist'].includes(route.path)
  }
  if (item.path === '/rank-product') {
    return route.path === '/rank-product' || route.path === '/rank-product/failures' || route.path === '/distribution'
  }
  return route.path === item.path
}

function navTitle(item) {
  return props.collapsed ? `${item.title} · ${item.desc}` : ''
}
</script>

<template>
  <aside class="layout-sidebar sidebar" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-header">
      <router-link to="/overview" class="brand brand-link" :title="collapsed ? '食品安全监督抽查数据统计' : ''">
        <div class="brand-mark">
          <img src="/favicon.svg" width="36" height="36" alt="" aria-hidden="true" class="brand-mark__icon" />
        </div>
        <div class="sidebar-brand-text brand-text">
          <h1>食品安全监督<br />抽查数据统计</h1>
        </div>
      </router-link>
      <button
        type="button"
        class="sidebar-toggle"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="emit('toggle')"
      >
        <el-icon>
          <Expand v-if="collapsed" />
          <Fold v-else />
        </el-icon>
      </button>
    </div>

    <div class="sidebar-body">
      <div class="nav-title">功能导航</div>
      <nav class="nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isNavActive(item) }"
          :title="navTitle(item)"
        >
          <span class="nav-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </span>
          <span class="nav-text">
            <span class="nav-item-title">{{ item.title }}</span>
            <span class="nav-item-desc">{{ item.desc }}</span>
          </span>
        </router-link>
      </nav>
    </div>

    <div class="sidebar-footer">
      <p class="footer-label">工具</p>
      <el-tooltip content="重新扫描数据" placement="right" :disabled="!collapsed" :show-after="200">
        <el-button type="primary" :loading="scanning" :icon="Refresh" @click="emit('scan')">
          <span class="btn-label">重新扫描数据</span>
        </el-button>
      </el-tooltip>
      <el-tooltip content="导出当前列表 CSV" placement="right" :disabled="!collapsed || !isListRoute()" :show-after="200">
        <el-button
          v-if="isListRoute()"
          plain
          class="btn-secondary"
          :icon="Download"
          :loading="exporting"
          :disabled="exporting"
          @click="emit('export')"
        >
          <span class="btn-label">{{ exporting ? '正在导出...' : '导出当前列表 CSV' }}</span>
        </el-button>
      </el-tooltip>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 16px 12px 16px;
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255, 255, 255, 0.45);
  box-shadow: 1px 0 0 rgba(226, 232, 240, 0.55);
  overflow: hidden;
  position: relative;
}

.sidebar-body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-header {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.55);
}

.sidebar-toggle {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  margin-top: 4px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  color: var(--app-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.sidebar-toggle:hover {
  color: var(--app-primary);
  border-color: rgba(191, 219, 254, 0.9);
  background: #fff;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 4px 0 0 6px;
  text-decoration: none;
  color: inherit;
  border-radius: 10px;
  transition: background 0.18s, padding 0.24s ease;
}

.brand-link:hover {
  background: rgba(255, 255, 255, 0.55);
}

.brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  overflow: hidden;
  box-shadow: 0 4px 14px rgba(91, 156, 245, 0.24);
}

.brand-mark__icon {
  width: 36px;
  height: 36px;
  display: block;
}

.brand-text {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  transition: opacity 0.2s ease, max-width 0.24s ease;
  max-width: 180px;
}

.brand-text h1 {
  margin: 0;
  font-family: var(--app-font-headline);
  font-size: 13px;
  line-height: 1.4;
  font-weight: 700;
  color: var(--app-text);
  letter-spacing: -0.015em;
}

.nav-title {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--app-text-muted);
  margin-bottom: 8px;
  padding: 0 8px;
  overflow: hidden;
  white-space: nowrap;
  transition: opacity 0.2s ease, max-height 0.24s ease, margin 0.24s ease;
  max-height: 24px;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 auto;
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  padding-bottom: 12px;
  -webkit-overflow-scrolling: touch;
}

.nav-item {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  padding: 9px 10px 9px 12px;
  border-radius: 10px;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
  box-sizing: border-box;
  flex-shrink: 0;
  transition: background 0.18s, color 0.18s, padding 0.24s ease;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.58);
}

.nav-item.active {
  background: rgba(91, 156, 245, 0.1);
}

.nav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 18px;
  border-radius: 0 2px 2px 0;
  background: var(--app-primary);
  transform: translateY(-50%);
}

.nav-icon {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: rgba(241, 245, 249, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--app-text-secondary);
  flex-shrink: 0;
  transition: background 0.18s, color 0.18s, transform 0.18s;
}

.nav-item:hover .nav-icon {
  background: rgba(255, 255, 255, 0.85);
  color: var(--app-primary);
  transform: scale(1.04);
}

.nav-item.active .nav-icon {
  background: rgba(91, 156, 245, 0.16);
  color: var(--app-primary);
}

.nav-text {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  transition: opacity 0.2s ease, max-width 0.24s ease;
  max-width: 180px;
}

.nav-item-title {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--app-text-secondary);
}

.nav-item-desc {
  display: block;
  font-size: 11px;
  color: var(--app-text-muted);
  margin-top: 1px;
  line-height: 1.35;
}

.nav-item.active .nav-item-title {
  font-weight: 600;
  color: var(--app-primary-dark);
}

.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-shrink: 0;
  padding-top: 12px;
  border-top: 1px solid rgba(226, 232, 240, 0.55);
  background: rgba(255, 255, 255, 0.72);
  pointer-events: auto;
}

.footer-label {
  margin: 0 0 2px;
  padding: 0 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--app-text-muted);
  overflow: hidden;
  white-space: nowrap;
  transition: opacity 0.2s ease, max-height 0.24s ease, margin 0.24s ease;
  max-height: 20px;
}

.sidebar-footer .el-button {
  width: 100%;
  margin: 0;
  border-radius: 8px;
  height: 38px;
  justify-content: flex-start;
  transition: width 0.24s ease, padding 0.24s ease;
}

.btn-label {
  transition: opacity 0.2s ease, max-width 0.24s ease;
  max-width: 200px;
  overflow: hidden;
  white-space: nowrap;
}

.btn-secondary {
  --el-button-bg-color: rgba(255, 255, 255, 0.6);
  --el-button-border-color: rgba(193, 198, 215, 0.6);
  --el-button-text-color: var(--app-text-secondary);
  --el-button-hover-bg-color: #f3f4f5;
}

.sidebar.is-collapsed {
  padding-left: 8px;
  padding-right: 8px;
}

.sidebar.is-collapsed .sidebar-header {
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
}

.sidebar.is-collapsed .brand-link {
  justify-content: center;
  padding: 0;
  gap: 0;
}

.sidebar.is-collapsed .sidebar-toggle {
  margin-top: 0;
}

.sidebar.is-collapsed .brand-text,
.sidebar.is-collapsed .nav-title,
.sidebar.is-collapsed .nav-text,
.sidebar.is-collapsed .footer-label,
.sidebar.is-collapsed .btn-label {
  opacity: 0;
  max-width: 0;
  pointer-events: none;
}

.sidebar.is-collapsed .nav-title,
.sidebar.is-collapsed .footer-label {
  max-height: 0;
  margin: 0;
}

.sidebar.is-collapsed .nav-item {
  justify-content: center;
  padding: 9px 8px;
}

.sidebar.is-collapsed .nav-item.active::before {
  left: 2px;
}

.sidebar.is-collapsed .sidebar-footer .el-button {
  width: 38px;
  min-width: 38px;
  padding-inline: 0;
  justify-content: center;
}

.sidebar.is-collapsed .sidebar-footer .el-button :deep(.el-icon) {
  margin: 0;
}
</style>
