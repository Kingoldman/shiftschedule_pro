<script setup>
import {
  ref,
  computed,
  onMounted,
  onBeforeUnmount,
  watch,
  nextTick,
} from "vue";
import dayjs from "dayjs";
import * as echarts from "echarts";
import { ElMessage } from "element-plus";
import { meApi } from "@/api/staff";
import { statsApi } from "@/api/schedule";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();

const loading = ref(false);
const months = ref([]);
const selectedMonth = ref(""); // 格式 YYYY-MM
const schedule = ref(null);

// 页签：month=当月班表（跟着月份走），stats=累计统计（跨月汇总）
// 之前两块内容平铺在同一个页面里，前半屏是当月、后半屏突然变成累计，
// 读起来像两个页面拼在一起，这里用页签把它们彻底分开。
const activeTab = ref("month");

// 个人统计（累计），搬自管理员「个人查询」
const employeeData = ref(null);

// ===== 图表 =====
const trendChartRef = ref(null);
const pieChartRef = ref(null);
let trendChart = null;
let pieChart = null;

const weekHeaders = ["一", "二", "三", "四", "五", "六", "日"];

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

// ===== 个人统计（搬自管理员个人查询）=====
function freqDescription(freq) {
  if (!freq || freq === 0) return "-";
  return `每${freq.toFixed(1)}天`;
}

function overviewFreqFormula(type) {
  const o = employeeData.value?.overview;
  if (!o) return "";
  const map = {
    workday: { eligible: "eligible_workday", count: "workday" },
    weekend: { eligible: "eligible_weekend", count: "weekend" },
    holiday: { eligible: "eligible_holiday", count: "holiday" },
    total: { eligible: "eligible_total", count: "total_duty_days" },
  };
  const m = map[type];
  if (!m) return "";
  return `${o[m.eligible] || 0}天统计 / ${o[m.count] || 0}天值班`;
}

const dayTypeMap = {
  workday: "工作日",
  weekend: "周末",
  holiday: "节假日",
  vacation: "调休补班",
};
function dayTypeLabel(t) {
  return dayTypeMap[t] || t;
}
function dayTypeColor(t) {
  return (
    {
      workday: "bg-gray-100 text-gray-600",
      weekend: "bg-blue-100 text-blue-700",
      holiday: "bg-red-100 text-red-600",
    }[t] || ""
  );
}
function weekdayLabel(dateStr) {
  const d = dayjs(dateStr);
  const names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  return names[d.day()];
}

// 所有值班记录：日期排序 + 性质筛选
const dutiesSortOrder = ref("asc"); // 日期排序：asc=旧→新（默认升序）
const dayTypeFilterValues = ref([]); // 性质筛选：空数组=全部
const filteredSortedDuties = computed(() => {
  let all = [...(employeeData.value?.all_duties || [])];
  if (dayTypeFilterValues.value.length > 0) {
    const set = new Set(dayTypeFilterValues.value);
    all = all.filter((d) => set.has(d.day_type));
  }
  return dutiesSortOrder.value === "asc"
    ? all.sort((a, b) => a.date.localeCompare(b.date))
    : all.sort((a, b) => b.date.localeCompare(a.date));
});
function toggleDutiesSort() {
  dutiesSortOrder.value = dutiesSortOrder.value === "asc" ? "desc" : "asc";
}
function onFilterChange(filters) {
  if (filters.day_type !== undefined) {
    dayTypeFilterValues.value = filters.day_type || [];
  }
}
const dayTypeFilters = [
  { text: "工作日(含调休补班)", value: "workday" },
  { text: "周末", value: "weekend" },
  { text: "节假日", value: "holiday" },
];

// ===== ECharts =====
function renderTrendChart() {
  if (!trendChartRef.value) return;
  if (!trendChart) trendChart = echarts.init(trendChartRef.value);
  const trend = employeeData.value?.monthly_trend || [];
  trendChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: ["工作日(含调休补班)", "周末", "节假日", "合计"], top: 0 },
    grid: { left: 36, right: 16, top: 40, bottom: 28 },
    xAxis: {
      type: "category",
      data: trend.map((m) => m.month),
      axisLabel: { fontSize: 11 },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 11 } },
    series: [
      {
        name: "工作日(含调休补班)",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: trend.map((m) => m.workday),
        itemStyle: { color: "#10b981" },
      },
      {
        name: "周末",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: trend.map((m) => m.weekend),
        itemStyle: { color: "#409eff" },
      },
      {
        name: "节假日",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        data: trend.map((m) => m.holiday),
        itemStyle: { color: "#ef4444" },
      },
      {
        name: "合计",
        type: "line",
        smooth: true,
        symbol: "circle",
        symbolSize: 7,
        data: trend.map((m) => m.total),
        itemStyle: { color: "#f59e0b" },
        lineStyle: { width: 3, type: "dashed" },
      },
    ],
  });
}

function renderPieChart() {
  if (!pieChartRef.value) return;
  if (!pieChart) pieChart = echarts.init(pieChartRef.value);
  const rawData = employeeData.value?.day_type_distribution || [];
  const data = rawData.map((d) => ({
    ...d,
    name: d.name === "工作日" ? "工作日(含调休补班)" : d.name,
  }));
  pieChart.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c}天 ({d}%)" },
    legend: {
      bottom: 0,
      left: "center",
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { fontSize: 12 },
    },
    series: [
      {
        type: "pie",
        radius: ["35%", "65%"],
        center: ["50%", "45%"],
        avoidLabelOverlap: true,
        label: { show: true, formatter: "{b}: {c}天", fontSize: 12 },
        data,
        color: ["#10b981", "#409eff", "#ef4444"],
      },
    ],
  });
}

async function renderCharts() {
  renderTrendChart();
  renderPieChart();
  // 切换页签后容器刚从隐藏变可见，DOM 虽已更新但浏览器布局尚未刷新，
  // echarts.init 时测到的宽度为 0，图表会缩在左侧，要等窗口 resize 才补正。
  // 这里等一帧（nextTick + requestAnimationFrame）布局就绪后再 resize 强制重测。
  await nextTick();
  requestAnimationFrame(() => {
    trendChart?.resize();
    pieChart?.resize();
  });
}

function handleResize() {
  trendChart?.resize();
  pieChart?.resize();
}

// ===== 数据加载 =====
async function loadMonths() {
  const list = await meApi.months();
  months.value = list || [];
  if (!selectedMonth.value && months.value.length) {
    // months 按时间倒序返回，第一个即最新月份
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

async function loadStats() {
  if (!auth.employeeId) return;
  try {
    employeeData.value = await statsApi.employee(auth.employeeId, "cumulative");
    dayTypeFilterValues.value = [];
    await nextTick();
    // 图表 DOM 只在「累计统计」页签首次激活后才存在，此时 ref 为 null，
    // renderCharts 内部会自行跳过，改由下面的 watch(activeTab) 补画
    renderCharts();
  } catch (e) {
    console.error("统计加载失败:", e);
  }
}

async function loadAll() {
  loading.value = true;
  try {
    await loadMonths();
    await loadSchedule();
    await loadStats();
  } catch (e) {
    console.error("加载失败:", e);
  } finally {
    loading.value = false;
  }
}

// 切到统计页签时补画图表（懒渲染的面板此时才挂载 DOM）
watch(activeTab, async (tab) => {
  if (tab !== "stats") return;
  await nextTick();
  renderCharts();
});

onMounted(() => {
  loadAll();
  window.addEventListener("resize", handleResize);
});
watch(selectedMonth, loadSchedule);

onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  trendChart?.dispose();
  pieChart?.dispose();
});

// 页头展示用：优先用统计接口返回的员工信息，未加载时回退到登录信息
const headerName = computed(
  () =>
    employeeData.value?.employee?.name ||
    auth.user?.employee_name ||
    auth.user?.username ||
    ""
);
const headerGroup = computed(() => employeeData.value?.employee?.group_name || "");
const headerState = computed(() => employeeData.value?.employee?.state);
const hasStats = computed(() => !!employeeData.value?.overview);
</script>

<template>
  <div class="p-6 max-w-6xl mx-auto space-y-5">
    <!-- 页头：身份信息（与月份无关，始终显示） -->
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-xl font-semibold text-gray-800">我的值班</h2>
        <div class="flex items-center gap-2 mt-1 text-sm text-gray-500 flex-wrap">
          <span class="font-medium text-gray-700">{{ headerName }}</span>
          <span
            v-if="headerState === 1"
            class="day-badge day-badge-workday"
            >值班中</span
          >
          <span
            v-else-if="headerState === 0"
            class="day-badge bg-gray-100 text-gray-500"
            >不值班</span
          >
          <template v-if="headerGroup">
            <span class="mx-1 text-gray-300">|</span>
            <span>{{ headerGroup }}</span>
          </template>
          <template v-if="hasStats">
            <span class="mx-1 text-gray-300">|</span>
            <span
              >累计
              <span class="num font-semibold text-gray-700">{{
                employeeData.overview.total_duty_days
              }}</span>
              天值班</span
            >
          </template>
        </div>
      </div>
      <div v-if="hasStats" class="text-xs text-gray-400">
        统计区间：<span class="text-gray-600">{{
          employeeData.period_range || "—"
        }}</span>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="my-duty-tabs">
      <!-- ===== 页签一：当月班表（随月份切换） ===== -->
      <el-tab-pane name="month">
        <template #label>
          <span>当月班表</span>
        </template>

        <div class="space-y-5 pt-1">
          <div class="flex items-center justify-between flex-wrap gap-3">
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
            <span
              v-if="schedule?.locked"
              class="px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700"
              >已发布</span
            >
            <span
              v-else-if="schedule"
              class="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500"
              >草稿</span
            >
          </div>

          <div
            v-if="!monthOptions.length && !loading"
            class="card p-16 text-center"
          >
            <el-icon size="40" class="text-gray-300 mb-3"><Calendar /></el-icon>
            <div class="text-gray-400 text-sm">暂无已发布的值班安排</div>
            <div class="text-gray-300 text-xs mt-1">
              管理员保存并发布排班后，这里会显示你的班表
            </div>
          </div>

          <template v-else>
            <!-- 当月概览 -->
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

            <!-- 值班日历 -->
            <div class="card">
              <div class="px-5 py-4 border-b border-gray-200">
                <div class="section-title">{{ monthLabel }} 值班日历</div>
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

            <!-- 当月明细 -->
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
                      >已发布</span
                    >
                    <span
                      v-else
                      class="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500"
                      >草稿</span
                    >
                  </template>
                </el-table-column>
                <template #empty>
                  <div class="py-10 text-sm text-gray-400">本月没有你的值班安排</div>
                </template>
              </el-table>
            </div>
          </template>
        </div>
      </el-tab-pane>

      <!-- ===== 页签二：累计统计（跨全部月份） ===== -->
      <el-tab-pane name="stats">
        <template #label>
          <span>累计统计</span>
        </template>

        <div class="space-y-5 pt-1">
          <div v-if="!hasStats" class="card p-16 text-center">
            <el-icon size="40" class="text-gray-300 mb-3"><DataAnalysis /></el-icon>
            <div class="text-gray-500 mb-2">暂无统计信息</div>
            <div class="text-xs text-gray-400">有已发布的值班记录后，这里会生成统计</div>
          </div>

          <template v-else>
            <div
              v-if="!employeeData.overview.total_duty_days"
              class="card p-16 text-center"
            >
              <el-icon size="40" class="text-gray-300 mb-3"><DataAnalysis /></el-icon>
              <div class="text-gray-500 mb-2">该区间暂无值班数据</div>
              <div class="text-xs text-gray-400">你还没有任何已发布的值班记录</div>
            </div>

            <template v-else>
              <!-- 概览数字卡片 -->
              <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">累计值班</div>
                  <div class="font-display text-2xl font-semibold num text-gray-800">
                    {{ employeeData.overview.total_duty_days }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">天</div>
                </div>
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">统计天数</div>
                  <div class="font-display text-2xl font-semibold num text-blue-600">
                    {{ employeeData.overview.eligible_total }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">
                    {{ employeeData.monthly_trend?.length || 0 }}个月累计
                  </div>
                </div>
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">工作日(含调休补班)频率</div>
                  <div class="font-display text-2xl font-semibold num text-green-600">
                    {{ freqDescription(employeeData.overview.freq_workday) }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">
                    {{ overviewFreqFormula("workday") }}
                  </div>
                </div>
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">周末频率</div>
                  <div class="font-display text-2xl font-semibold num text-blue-600">
                    {{ freqDescription(employeeData.overview.freq_weekend) }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">
                    {{ overviewFreqFormula("weekend") }}
                  </div>
                </div>
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">节假日频率</div>
                  <div class="font-display text-2xl font-semibold num text-red-500">
                    {{ freqDescription(employeeData.overview.freq_holiday) }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">
                    {{ overviewFreqFormula("holiday") }}
                  </div>
                </div>
                <div class="card p-4">
                  <div class="text-xs text-gray-500 mb-1">综合频率</div>
                  <div class="font-display text-2xl font-semibold num text-amber-600">
                    {{ freqDescription(employeeData.overview.frequency) }}
                  </div>
                  <div class="text-[10px] text-gray-400 mt-1">
                    {{ overviewFreqFormula("total") }}
                  </div>
                </div>
              </div>

              <!-- 图表区：上下两行，避免展示不全 -->
              <div class="grid grid-cols-1 gap-4">
                <div class="card p-4">
                  <div class="section-title mb-3">月度值班趋势</div>
                  <div ref="trendChartRef" style="width: 100%; height: 300px"></div>
                </div>
                <div class="card p-4">
                  <div class="section-title mb-3">日期性质分布</div>
                  <div ref="pieChartRef" style="width: 100%; height: 300px"></div>
                </div>
              </div>

              <!-- 所有值班记录（日期可排序 + 性质可筛选） -->
              <div class="card">
                <div
                  class="px-5 py-4 border-b border-gray-200 flex items-center justify-between"
                >
                  <div class="section-title">所有值班记录</div>
                  <div class="text-xs text-gray-500">
                    共
                    <span class="num font-semibold text-gray-700">{{
                      filteredSortedDuties.length
                    }}</span>
                    条
                  </div>
                </div>
                <el-table
                  :data="filteredSortedDuties"
                  style="width: 100%"
                  size="small"
                  max-height="520"
                  @filter-change="onFilterChange"
                >
                  <el-table-column label="日期" prop="date" width="120">
                    <template #header>
                      <span
                        class="cursor-pointer select-none flex items-center gap-1"
                        @click="toggleDutiesSort"
                      >
                        日期
                        <span
                          :style="`color:${dutiesSortOrder === 'asc' ? '#10b981' : '#409eff'};font-weight:bold`"
                        >
                          {{ dutiesSortOrder === "asc" ? "↑" : "↓" }}
                        </span>
                      </span>
                    </template>
                    <template #default="{ row }">
                      <span class="num font-medium">{{ row.date }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="星期" width="80" align="center">
                    <template #default="{ row }">
                      <span class="text-gray-500 text-xs">{{
                        weekdayLabel(row.date)
                      }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column
                    label="性质"
                    prop="day_type"
                    column-key="day_type"
                    width="120"
                    align="center"
                    :filters="dayTypeFilters"
                    :filter-method="(value, row) => row.day_type === value"
                  >
                    <template #default="{ row }">
                      <span class="day-badge" :class="dayTypeColor(row.day_type)">{{
                        dayTypeLabel(row.day_type)
                      }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="值班组" prop="group_name" width="140">
                    <template #default="{ row }">
                      <span class="font-medium">{{ row.group_name || "-" }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="同班人员">
                    <template #default="{ row }">
                      <span
                        v-if="(row.coworkers || []).length === 0"
                        class="text-gray-400 text-xs"
                        >单独值班</span
                      >
                      <span v-else class="text-gray-700">{{
                        (row.coworkers || []).join("、")
                      }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </template>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
/* 页签与下方内容留白对齐，卡片风格与全站一致 */
.my-duty-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}
.my-duty-tabs :deep(.el-tabs__nav-wrap)::after {
  height: 1px;
  background-color: #e5e7eb;
}
</style>
