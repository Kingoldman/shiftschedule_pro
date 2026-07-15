<script setup>
import { ref, computed, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessageBox, ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

// 侧边栏菜单：从路由 meta 生成
const menus = computed(() =>
  router.options.routes
    .find((r) => r.path === '/')
    .children.map((r) => ({
      path: `/${r.path}`,
      name: r.name,
      title: r.meta.title,
      icon: r.meta.icon,
    }))
)

const collapsed = ref(false)

// ===== 登录弹窗 =====
// 不再硬编码默认账号密码，避免在浏览器端泄漏默认凭据
const loginForm = reactive({ username: '', password: '' })
const loginLoading = ref(false)

function openLoginDialog() {
  auth.loginDialogVisible = true
}

async function handleLogin() {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loginLoading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    auth.loginDialogVisible = false
  } catch (e) {
    const status = e?.response?.status
    if (status === 401) {
      ElMessage.error('账号或密码错误')
    }
  } finally {
    loginLoading.value = false
  }
}

// ===== 修改密码弹窗 =====
const pwdDialogVisible = ref(false)
const pwdForm = ref({ old: '', new: '', confirm: '' })

async function handleChangePassword() {
  if (!pwdForm.value.old || !pwdForm.value.new) {
    ElMessage.warning('请填写完整')
    return
  }
  if (pwdForm.value.new !== pwdForm.value.confirm) {
    ElMessage.warning('两次密码不一致')
    return
  }
  try {
    await auth.changePassword(pwdForm.value.old, pwdForm.value.new)
    ElMessage.success('密码已修改，请重新登录')
    pwdDialogVisible.value = false
    auth.logout()
  } catch (e) {
    // 错误已在拦截器统一提示
  }
}

function handleLogout() {
  ElMessageBox.confirm('确定要退出登录吗？', '提示', {
    type: 'warning',
  }).then(() => {
    auth.logout()
    ElMessage.success('已退出登录')
  }).catch(() => {})
}
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <!-- 侧边栏：深蓝背景，与 Element Plus #409EFF 同色系，简洁不花哨 -->
    <aside
      class="flex flex-col text-white transition-all duration-300"
      :class="collapsed ? 'w-16' : 'w-56'"
      style="background: #1a2a44"
    >
      <!-- Logo 区 -->
      <div class="h-16 flex items-center gap-3 px-4" style="border-bottom: 1px solid rgba(255,255,255,0.06)">
        <div class="w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0" style="background: #409eff">
          <svg viewBox="0 0 24 24" class="w-5 h-5 text-white" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="9" />
            <line x1="12" y1="12" x2="12" y2="7" stroke-linecap="round" />
            <line x1="12" y1="12" x2="16" y2="12" stroke-linecap="round" />
          </svg>
        </div>
        <div class="overflow-hidden whitespace-nowrap transition-opacity duration-200" :class="collapsed ? 'opacity-0 w-0' : 'opacity-100'">
          <div class="font-display font-semibold text-base leading-tight">隔壁小王爱值班</div>
          <div class="text-[10px] tracking-widest uppercase" style="color: rgba(255,255,255,0.35)">Shift Schedule</div>
        </div>
      </div>

      <!-- 菜单 -->
      <nav class="flex-1 py-4 space-y-1 overflow-hidden">
        <el-tooltip
          v-for="m in menus"
          :key="m.path"
          :content="m.title"
          placement="right"
          :disabled="!collapsed"
          :show-after="200"
        >
          <router-link
            :to="m.path"
            class="flex items-center gap-3 px-4 py-2.5 mx-2 rounded-md text-sm transition-all duration-200"
            :class="route.path === m.path
              ? 'font-medium'
              : 'hover:bg-white/5'"
            :style="route.path === m.path
              ? 'background: #409eff; color: #fff'
              : 'color: rgba(255,255,255,0.55)'"
          >
            <el-icon class="text-base flex-shrink-0">
              <component :is="m.icon" />
            </el-icon>
            <span class="whitespace-nowrap transition-opacity duration-200" :class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'">{{ m.title }}</span>
          </router-link>
        </el-tooltip>
      </nav>

      <!-- 用户区 -->
      <div class="border-t p-2" style="border-color: rgba(255,255,255,0.06)">
        <!-- 已登录 -->
        <template v-if="auth.isLoggedIn">
          <el-tooltip :content="`${auth.admin?.username || '管理员'}（点击修改密码）`" placement="right" :disabled="!collapsed" :show-after="200">
            <div class="flex items-center gap-2 px-2 py-2 rounded-md cursor-pointer transition-colors hover:bg-white/5" style="color: rgba(255,255,255,0.55)" @click="pwdDialogVisible = true">
              <div class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0" style="background: rgba(64,158,255,0.15); color: #409eff">
                {{ auth.admin?.username?.[0]?.toUpperCase() || 'A' }}
              </div>
              <div class="flex-1 overflow-hidden whitespace-nowrap transition-opacity duration-200" :class="collapsed ? 'opacity-0 w-0' : 'opacity-100'">
                <div class="text-sm text-white truncate">{{ auth.admin?.username || '管理员' }}</div>
                <div class="text-[10px]" style="color: rgba(255,255,255,0.35)">点击修改密码</div>
              </div>
            </div>
          </el-tooltip>
          <el-tooltip content="退出登录" placement="right" :disabled="!collapsed" :show-after="200">
            <button
              class="w-full mt-2 px-3 py-1.5 text-xs transition-colors flex items-center justify-center gap-1 hover:text-red-400"
              style="color: rgba(255,255,255,0.35)"
              @click="handleLogout"
            >
              <el-icon class="flex-shrink-0"><SwitchButton /></el-icon>
              <span class="whitespace-nowrap transition-opacity duration-200" :class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'">退出登录</span>
            </button>
          </el-tooltip>
        </template>
        <!-- 未登录：打开登录弹窗 -->
        <template v-else>
          <el-tooltip content="管理员登录" placement="right" :disabled="!collapsed" :show-after="200">
            <button
              class="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm transition-colors hover:bg-white/5"
              style="color: rgba(255,255,255,0.55)"
              @click="openLoginDialog"
            >
              <el-icon class="flex-shrink-0"><User /></el-icon>
              <span class="whitespace-nowrap transition-opacity duration-200" :class="collapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'">管理员登录</span>
            </button>
          </el-tooltip>
        </template>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- 顶部栏 -->
      <header class="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 flex-shrink-0">
        <div class="flex items-center gap-3">
          <button
            class="p-1.5 rounded hover:bg-gray-100 text-gray-500"
            @click="collapsed = !collapsed"
          >
            <el-icon size="18">
              <Fold v-if="!collapsed" />
              <Expand v-else />
            </el-icon>
          </button>
          <div class="text-sm text-gray-500">
            <span class="num">{{ new Date().getFullYear() }}</span> 年
          </div>
        </div>
        <div class="flex items-center gap-4">
          <span v-if="!auth.isLoggedIn" class="text-xs text-gray-400">
            未登录 · 仅可查看
          </span>
          <span class="text-xs text-gray-400 font-mono tracking-wider">
            {{ new Date().toLocaleDateString('zh-CN', { weekday: 'long' }) }}
          </span>
        </div>
      </header>

      <!-- 路由出口 -->
      <main class="flex-1 overflow-auto" style="scrollbar-gutter: stable">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- 登录弹窗 -->
    <el-dialog v-model="auth.loginDialogVisible" title="管理员登录" width="400px">
      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1.5">用户名</label>
          <el-input v-model="loginForm.username" placeholder="请输入用户名" size="large" />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 mb-1.5">密码</label>
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </div>
        <button
          type="submit"
          class="w-full btn-primary py-3 text-base"
          :disabled="loginLoading"
        >
          <span v-if="loginLoading" class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          {{ loginLoading ? '登录中...' : '登 录' }}
        </button>
      </form>
      <div class="mt-4 text-xs text-gray-400 text-center">
        首次启动时请查看后端日志获取初始管理员密码
      </div>
    </el-dialog>

    <!-- 修改密码弹窗 -->
    <el-dialog v-model="pwdDialogVisible" title="修改密码" width="400px">
      <el-form label-width="80px" label-position="right">
        <el-form-item label="旧密码">
          <el-input v-model="pwdForm.old" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="pwdForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <button class="btn-ghost" @click="pwdDialogVisible = false">取消</button>
        <button class="btn-primary ml-2" @click="handleChangePassword">确认</button>
      </template>
    </el-dialog>
  </div>
</template>
