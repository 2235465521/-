import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: 'overview',
    component: () => import('@/views/OverviewView.vue'),
    meta: { title: '数据总览', desc: '汇总合格与不合格抽检数据概览' },
  },
  {
    path: '/qualified',
    name: 'qualified',
    component: () => import('@/views/ListView.vue'),
    meta: { title: '合格汇总', desc: '合格批次明细，支持单位/产品/分类筛选', type: 'qualified' },
  },
  {
    path: '/unqualified',
    name: 'unqualified',
    component: () => import('@/views/ListView.vue'),
    meta: { title: '不合格汇总', desc: '不合格项目明细与原因分析', type: 'unqualified' },
  },
  {
    path: '/rank-product',
    name: 'rank-product',
    component: () => import('@/views/ProductRankView.vue'),
    meta: { title: '产品榜单', desc: '产品不合格率、不合格项目、高频违规产品' },
  },
  {
    path: '/rank-unit',
    name: 'rank-unit',
    component: () => import('@/views/UnitRankView.vue'),
    meta: { title: '单位红绿榜', desc: '被抽检单位与生产单位红榜、绿榜分开统计' },
  },
  {
    path: '/rank-unit/failures',
    name: 'unit-failures',
    component: () => import('@/views/FailureDetailView.vue'),
    meta: { title: '单位不合格明细', desc: '查看红榜单位的不合格项目与原因' },
  },
  {
    path: '/rank-product/failures',
    name: 'product-failures',
    component: () => import('@/views/FailureDetailView.vue'),
    meta: { title: '产品不合格明细', desc: '查看产品的不合格记录与源文件' },
  },
  {
    path: '/greenlist',
    name: 'greenlist',
    redirect: { name: 'rank-unit' },
    meta: { title: '绿榜全合格', desc: '已合并至单位红绿榜' },
  },
  { path: '/rank', redirect: '/rank-unit' },
  { path: '/distribution', redirect: { name: 'rank-product', query: { tab: 'item_types' } } },
  { path: '/alert', redirect: '/rank-unit' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
