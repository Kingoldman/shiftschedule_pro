import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/schedule',
    children: [
      {
        path: 'my',
        name: 'my',
        component: () => import('@/views/MyDuty.vue'),
        meta: { title: '我的值班', icon: 'Calendar', roles: ['employee'] },
      },
      {
        path: 'staff',
        name: 'staff',
        component: () => import('@/views/StaffManage.vue'),
        meta: { title: '人员管理', icon: 'User', roles: ['admin'] },
      },
      {
        path: 'days',
        name: 'days',
        component: () => import('@/views/DaySetup.vue'),
        meta: { title: '日期设置', icon: 'Calendar', roles: ['admin'] },
      },
      {
        path: 'schedule',
        name: 'schedule',
        component: () => import('@/views/ScheduleMake.vue'),
        meta: { title: '排班管理', icon: 'List', roles: ['admin'] },
      },
      {
        path: 'stats',
        name: 'stats',
        component: () => import('@/views/Stats.vue'),
        meta: { title: '统计分析', icon: 'DataAnalysis', roles: ['admin'] },
      },
      {
        path: 'person',
        name: 'person',
        component: () => import('@/views/PersonDuty.vue'),
        meta: { title: '个人查询', icon: 'UserFilled', roles: ['admin'] },
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

// 导航守卫：登录校验 + 角色校验
//
// 注意：登录采用的是弹窗形式、没有独立的登录页，所以未登录时**不能**重定向到
// /login——那会造成"跳走 → 判定未登录 → 再跳走"的死循环。
// 正确做法是放行导航并弹出登录框；真正的接口鉴权由后端 401 兜底。
//
// 前端的角色拦截只是体验优化，防止员工点到管理页看到一片空白；
// 即便绕过去，后端也会返回 403，不会泄漏数据。
router.beforeEach((to) => {
  const auth = useAuthStore()

  if (!auth.isLoggedIn) {
    if (!auth.loginDialogVisible) auth.loginDialogVisible = true
    return
  }

  const allowed = to.meta.roles
  if (allowed && !allowed.includes(auth.role)) {
    return auth.role === 'employee' ? '/my' : '/schedule'
  }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 隔壁小王爱值班` : '隔壁小王爱值班'
})

export default router
