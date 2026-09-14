<script setup>
import { ref, computed, onMounted, watch } from "vue";
import dayjs from "dayjs";
import { ElMessage, ElMessageBox } from "element-plus";
import { meApi } from "@/api/staff";
import { statsApi } from "@/api/schedule";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();

const loading = ref(false);
const months = ref([]);
const selectedMonth = ref(""); // 格式 YYYY-MM
const schedule = ref(null);
const cumulative = ref(null);

// 日历订阅
const feed = ref({ enabled: false, path: null, updated_at: null });
const feedBusy = ref(false);
const showGuide = ref([]); // el-collapse 的 v-model 需要数组

// 后端返回的是相对路径，拼上当前站点地址才是日历客户端能访问的地址
const feedUrl = computed(() =>
  feed.value.path ? window.location.origin + feed.value.path : ""
);
// 下载 .ics 走登录态，浏览器会自动带上 Cookie
const icsDownloadUrl = computed(() => {
  if (!selectedMonth.value) return "/api/me/ics";
  const [y, m] = selectedMonth.value.split("-");
  return `/api/me/ics?year=${y}&month=${Number(m)}`;
});

// 值班日 -> 该日信息，用于月历快速查表
const dutyMap = computed(() => {
  const map = {};
  for (const d of schedule.value?.days || []) map[d.date] = d;
  return map;
});

const monthOptions = computed(() =>
  months.value.map((m) => ({
    value: `${m.year}-${String(m.month).padStart(2, "0")}`,
    label: `${m.year} 年 ${m.month} 月`,
  }))
);

const monthLabel = computed(() => {
  const opt = monthOptions.value.find((o) => o.value === selectedMonth.value);
  return opt?.label || "";
});

// 月历格子：周一为一周起始，前后补空位
const calendarCells = computed(() => {
  if (!selectedMonth.value) return [];
  const first = dayjs(selectedMonth.value + "-01");
  const daysInMonth = first.daysInMonth();
  // dayjs day(): 0=周日，转换为以周一为 0
  const leading = (first.day() + 6) % 7;
  const cells = [];
  for (let i = 0; i < leading; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = first.date(d).format("YYYY-MM-DD");
    cells.push({ day: d, date: dateStr, duty: dutyMap.value[dateStr] || null });
  }
  return cells;
});

const weekHeaders = ["一", "二", "三", "四", "五", "六", "日"];

const summary = computed(
  () =>
    schedule.value?.summary || {
      workday: 0,
      weekend: 0,
      holiday: 0,
      total: 0,
    }
);

function dayTypeClass(type) {
  return `day-badge day-badge-${type}`;
}

async function loadMonths() {
  const list = await meApi.months();
  months.value = list || [];
  if (!selectedMonth.value && months.value.length) {
    selectedMonth.value = `${months.value[0].year}-${String(
      months.value[0].month
    ).padStart(2, "0")}`;
  }
}

async function loadSchedule() {
  if (!selectedMonth.value) {
    schedule.value = null;
    return;
  }
  const [y, m] = selectedMonth.value.split("-").map(Number);
  schedule.value = await meApi.schedule(y, m);
}

async function loadCumulative() {
  if (!auth.employeeId) return;
  cumulative.value = await statsApi.employee(auth.employeeId, "cumulative");
}

async function loadFeed() {
  try {
    feed.value = await meApi.feedUrl();
  } catch {
    feed.value = { enabled: false, path: null, updated_at: null };
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 降级到 execCommand */
  }
  // http 页面（如局域网 IP 访问）下 clipboard API 不可用，用隐藏输入框兜底
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

async function copyFeed() {
  const ok = await copyText(feedUrl.value);
  ElMessage[ok ? "success" : "warning"](
    ok ? "订阅地址已复制" : "复制失败，请手动选中地址复制"
  );
}

async function enableFeed() {
  feedBusy.value = true;
  try {
    feed.value = await meApi.rotateFeed();
    ElMessage.success("订阅已开启");
  } catch (e) {
    console.error("操作失败:", e);
  } finally {
    feedBusy.value = false;
  }
}

async function rotateFeed() {
  try {
    await ElMessageBox.confirm(
      "重新生成后，旧的订阅地址立即失效，已订阅的日历需要重新添加。确定继续？",
      "重新生成订阅地址",
      { type: "warning", confirmButtonText: "重新生成", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  feedBusy.value = true;
  try {
    feed.value = await meApi.rotateFeed();
    ElMessage.success("已生成新的订阅地址");
  } catch (e) {
    console.error("操作失败:", e);
  } finally {
    feedBusy.value = false;
  }
}

async function revokeFeed() {
  try {
    await ElMessageBox.confirm(
      "停用后所有已订阅的日历将拉取不到班表，可随时重新开启。确定停用？",
      "停用日历订阅",
      { type: "warning", confirmButtonText: "停用", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }
  feedBusy.value = true;
  try {
    feed.value = await meApi.revokeFeed();
    ElMessage.success("订阅已停用");
  } catch (e) {
    console.error("操作失败:", e);
  } finally {
    feedBusy.value = false;
  }
}

async function loadAll() {
  loading.value = true;
  try {
    await loadMonths();
    await loadSchedule();
    await loadCumulative();
    await loadFeed();
  } catch (e) {
    console.error("加载失败:", e);
  } finally {
    loading.value = false;
  }
}

onMounted(loadAll);
watch(selectedMonth, loadSchedule);
</script>

<template>
  <div class="p-6 space-y-5 max-w-6xl">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-xl font-semibold text-gray-800">我的值班</h2>
        <p class="text-sm text-gray-400 mt-1">
          {{ auth.user?.employee_name || auth.user?.username }} · 仅显示本人安排
        </p>
      </div>
      <el-select
        v-model="selectedMonth"
        placeholder="选择月份"
        size="default"
        style="width: 160px"
        :disabled="!monthOptions.length"
      >
        <el-option
          v-for="o in monthOptions"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>
    </div>

    <div v-if="!monthOptions.length && !loading" class="card p-16 text-center">
      <el-icon size="40" class="text-gray-300 mb-3"><Calendar /></el-icon>
      <div class="text-gray-400 text-sm">暂无已发布的值班安排</div>
      <div class="text-gray-300 text-xs mt-1">
        管理员保存并发布排班后，这里会显示你的班表
      </div>
    </div>

    <template v-else>
      <!-- 本月概览 -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="card p-4">
          <div class="text-xs text-gray-400 mb-1">{{ monthLabel }} 值班</div>
          <div class="text-2xl font-semibold text-gray-800 num">
            {{ summary.total }}
          </div>
          <div class="text-xs text-gray-400 mt-0.5">天</div>
        </div>
        <div class="card p-4">
          <div class="text-xs text-gray-400 mb-1">工作日</div>
          <div class="text-2xl font-semibold text-gray-700 num">
            {{ summary.workday }}
          </div>
          <div class="text-xs text-gray-400 mt-0.5">含调休补班</div>
        </div>
        <div class="card p-4">
          <div class="text-xs text-gray-400 mb-1">周末</div>
          <div class="text-2xl font-semibold text-blue-600 num">
            {{ summary.weekend }}
          </div>
          <div class="text-xs text-gray-400 mt-0.5">天</div>
        </div>
        <div class="card p-4">
          <div class="text-xs text-gray-400 mb-1">节假日</div>
          <div class="text-2xl font-semibold text-red-500 num">
            {{ summary.holiday }}
          </div>
          <div class="text-xs text-gray-400 mt-0.5">天</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <!-- 月历 -->
        <div class="card lg:col-span-3">
          <div class="px-5 py-4 border-b border-gray-200">
            <div class="section-title">值班日历</div>
          </div>
          <div class="p-5" v-loading="loading">
            <div class="grid grid-cols-7 mb-2">
              <div
                v-for="w in weekHeaders"
                :key="w"
                class="text-center text-xs text-gray-400 py-1"
              >
                {{ w }}
              </div>
            </div>
            <div class="grid grid-cols-7 gap-1">
              <div v-for="(cell, i) in calendarCells" :key="i" class="aspect-square">
                <div
                  v-if="cell"
                  class="w-full h-full rounded-md border flex flex-col items-center justify-center text-sm"
                  :class="cell.duty
                    ? 'border-blue-200 bg-blue-50'
                    : 'border-transparent text-gray-400'"
                >
                  <span class="num" :class="cell.duty ? 'text-blue-700 font-semibold' : ''">
                    {{ cell.day }}
                  </span>
                  <span
                    v-if="cell.duty"
                    class="mt-0.5 w-1.5 h-1.5 rounded-full"
                    :class="{
                      'bg-gray-400': cell.duty.day_type === 'workday' || cell.duty.day_type === 'vacation',
                      'bg-blue-500': cell.duty.day_type === 'weekend',
                      'bg-red-500': cell.duty.day_type === 'holiday',
                    }"
                  ></span>
                </div>
              </div>
            </div>
            <div class="mt-4 flex items-center gap-4 text-xs text-gray-500 flex-wrap">
              <span class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-gray-400"></span>工作日
              </span>
              <span class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-blue-500"></span>周末
              </span>
              <span class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-red-500"></span>节假日
              </span>
            </div>
          </div>
        </div>

        <!-- 累计统计 -->
        <div class="card lg:col-span-2">
          <div class="px-5 py-4 border-b border-gray-200">
            <div class="section-title">累计概览</div>
          </div>
          <div class="p-5 space-y-3" v-loading="loading">
            <div
              v-if="!cumulative || !cumulative.overview"
              class="py-8 text-center text-sm text-gray-400"
            >
              暂无统计
            </div>
            <template v-else>
              <div class="flex items-center justify-between py-2 border-b border-gray-100">
                <span class="text-sm text-gray-500">累计值班</span>
                <span class="num text-lg font-semibold text-gray-800">
                  {{ cumulative.overview.total_duty_days }}
                </span>
              </div>
              <div class="flex items-center justify-between py-2 border-b border-gray-100">
                <span class="text-sm text-gray-500">工作日</span>
                <span class="num text-gray-700">{{ cumulative.overview.workday }}</span>
              </div>
              <div class="flex items-center justify-between py-2 border-b border-gray-100">
                <span class="text-sm text-gray-500">周末</span>
                <span class="num text-blue-600">{{ cumulative.overview.weekend }}</span>
              </div>
              <div class="flex items-center justify-between py-2 border-b border-gray-100">
                <span class="text-sm text-gray-500">节假日</span>
                <span class="num text-red-500">{{ cumulative.overview.holiday }}</span>
              </div>
              <div class="text-xs text-gray-400 pt-2">
                统计区间：{{ cumulative.period_range || "—" }}
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 明细 -->
      <div class="card">
        <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div class="section-title">{{ monthLabel }} 值班明细</div>
          <span class="text-xs text-gray-400">共 {{ summary.total }} 天</span>
        </div>
        <el-table :data="schedule?.days || []" v-loading="loading" style="width: 100%">
          <el-table-column label="日期" min-width="130">
            <template #default="{ row }">
              <span class="num text-sm">{{ row.date }}</span>
              <span class="text-xs text-gray-400 ml-2">{{ row.weekday }}</span>
            </template>
          </el-table-column>
          <el-table-column label="日期性质" min-width="110" align="center">
            <template #default="{ row }">
              <span :class="dayTypeClass(row.day_type)">{{ row.day_type_label }}</span>
            </template>
          </el-table-column>
          <el-table-column label="值班组" min-width="140">
            <template #default="{ row }">
              <span class="text-sm">{{ row.group_name || "—" }}</span>
            </template>
          </el-table-column>
          <el-table-column label="同班同事" min-width="220">
            <template #default="{ row }">
              <span v-if="row.coworkers?.length" class="text-sm text-gray-600">
                {{ row.coworkers.join("、") }}
              </span>
              <span v-else class="text-sm text-gray-400">单独值班</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="90" align="center">
            <template #default>
              <span
                v-if="schedule?.locked"
                class="px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700"
              >
                已发布
              </span>
              <span
                v-else
                class="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500"
              >
                草稿
              </span>
            </template>
          </el-table-column>
          <template #empty>
            <div class="py-10 text-sm text-gray-400">本月没有你的值班安排</div>
          </template>
        </el-table>
      </div>

      <!-- 日历订阅 -->
      <div class="card">
        <div
          class="px-5 py-4 border-b border-gray-200 flex items-center justify-between"
        >
          <div class="section-title">日历订阅</div>
          <span
            class="px-2 py-0.5 rounded text-xs font-medium"
            :class="feed.enabled
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-100 text-gray-500'"
          >
            {{ feed.enabled ? "已开启" : "未开启" }}
          </span>
        </div>
        <div class="p-5 space-y-4">
          <div v-if="!feed.enabled" class="flex items-center justify-between gap-4 flex-wrap">
            <div class="text-sm text-gray-500">
              订阅后，值班安排会自动同步到手机或电脑日历，班表调整后无需再手动添加。
            </div>
            <button class="btn-primary flex-shrink-0" :disabled="feedBusy" @click="enableFeed">
              开启订阅
            </button>
          </div>

          <template v-else>
            <div class="flex items-center gap-2 flex-wrap">
              <el-input :model-value="feedUrl" readonly size="default" class="flex-1 min-w-[260px]">
                <template #prepend>订阅地址</template>
              </el-input>
              <button class="btn-ghost flex-shrink-0" @click="copyFeed">
                <el-icon><DocumentCopy /></el-icon>复制
              </button>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              <a :href="icsDownloadUrl" class="btn-ghost no-underline">
                <el-icon><Download /></el-icon>下载 .ics 文件
              </a>
              <button class="btn-ghost" :disabled="feedBusy" @click="rotateFeed">
                <el-icon><Refresh /></el-icon>重新生成
              </button>
              <button class="btn-ghost text-red-500" :disabled="feedBusy" @click="revokeFeed">
                <el-icon><CircleClose /></el-icon>停用订阅
              </button>
              <span v-if="feed.updated_at" class="text-xs text-gray-400">
                生成于 {{ feed.updated_at.replace("T", " ").slice(0, 16) }}
              </span>
            </div>
            <div class="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              订阅地址里含个人密钥，请勿转发他人；重新生成后旧地址立即失效。
              若要在手机上订阅，请把地址中的
              <span class="font-mono">localhost</span>
              换成后端所在电脑的局域网 IP（例如
              <span class="font-mono">http://192.168.1.10:8000</span>）。
            </div>
          </template>

          <el-collapse v-model="showGuide">
            <el-collapse-item name="guide" title="怎么添加到日历？">
              <div class="text-sm text-gray-600 space-y-2 pb-2">
                <div>
                  <span class="font-medium text-gray-700">iPhone / Mac 系统日历</span>：
                  设置 → 日历 → 账户 → 添加账户 → 其他 →「添加已订阅的日历」，粘贴上面的地址。
                </div>
                <div>
                  <span class="font-medium text-gray-700">安卓（Google 日历）</span>：
                  手机 App 不支持直接订阅。请在电脑上打开
                  <span class="font-mono">calendar.google.com</span>
                  → 左侧「其他日历」旁的 + → 通过网址添加，加完后手机会自动同步。
                </div>
                <div>
                  <span class="font-medium text-gray-700">Windows</span>：
                  系统自带「日历」应用不支持订阅，请用 Outlook ——
                  新版 Outlook / Outlook 网页版：添加日历 → 从 Web 订阅；
                  经典版 Outlook：文件 → 账户设置 → Internet 日历 → 新建。
                </div>
                <div>
                  <span class="font-medium text-gray-700">不支持订阅的客户端</span>：
                  用上面的「下载 .ics 文件」导入即可，
                  但这是一次性快照，班表变动不会自动更新。
                </div>
                <div class="text-xs text-gray-400 pt-1">
                  订阅是只读的，日历客户端通常每几小时自动刷新一次；
                  想立即看到最新班表可在客户端手动刷新。
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </template>
  </div>
</template>
