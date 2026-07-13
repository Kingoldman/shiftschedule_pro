import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/schedule',
    children: [
      {
        path: 'staff',
        name: 'staff',
        component: () => import('@/views/StaffManage.vue'),
        meta: { title: '人员管理', icon: 'User' },
      },
      {
        path: 'days',
        name: 'days',
        component: () => import('@/views/DaySetup.vue'),
        meta: { title: '日期设置', icon: 'Calendar' },
      },
      {
        path: 'schedule',
        name: 'schedule',
        component: () => import('@/views/ScheduleMake.vue'),
        meta: { title: '排班管理', icon: 'List' },
      },
      {
        path: 'stats',
        name: 'stats',
        component: () => import('@/views/Stats.vue'),
        meta: { title: '统计分析', icon: 'DataAnalysis' },
      },
      {
        path: 'person',
        name: 'person',
        component: () => import('@/views/PersonDuty.vue'),
        meta: { title: '个人查询', icon: 'UserFilled' },
      },
    ],
  },
  // 旧 /login 路径重定向到首页（登录已改为弹窗）
  {
    path: '/login',
    redirect: '/schedule',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 隔壁小王爱值班` : '隔壁小王爱值班'
})

export default router
