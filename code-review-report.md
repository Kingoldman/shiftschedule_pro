# 代码审查报告：隔壁小王爱值班（shiftschedule_pro）

> 审查方式：通读后端 `app/` 全部源码 + 前端 `src/` 全部源码，并对最严重项逐一对照原文核实。
> 审查范围：仅分析，未修改任何代码。
> 项目规模：后端 ~2,378 行（30 个 `.py`）、前端 `src` ~5,120 行（21 个源文件）；整体为 FastAPI + Vue3 全栈。

---

## 一、总体评价

这是一套**业务闭环非常完整、作者对排班领域理解很深**的内部工具：编组轮转、日期性质冻结、快照回溯、Excel 导入校验、频率统计、PDF 报告分页切片，细节做得很到位。ORM 用法、bcrypt 哈希、JWT 算法选择都是正确的方向。

但风险集中在四块，每块都有一个会**直接导致事故或错误结论**的硬伤：

1. **安全默认值** —— JWT 默认密钥硬编码、默认弱口令、读接口全裸奔。
2. **数据完整性** —— SQLite 外键级联从未真正启用，删除员工会留下孤儿日志。
3. **输入边界** —— 批量导入/排序接口用 `list[dict]` 零校验，畸形请求直接 500。
4. **统计正确性** —— `compute_eligible_days` 全员"应值班天数"相同，频率指标失真，`EmployeeStateLog` 形同死代码。

以下按严重度分级，**所有引用均带文件:行号，关键项已逐字核对源码**。

---

## 二、严重问题（Critical / High）—— 建议优先处理

### 🔴 C1【Critical】JWT 默认密钥硬编码，可被伪造 Token 直接登录
`backend/app/core/config.py:22`
```python
SECRET_KEY: str = "shiftschedule-secret-key-change-in-production"
```
该值是 `Settings` 字段默认值，仅在存在 `.env` 且显式设置时才会被覆盖。项目只随附 `.env.example`，**并没有真正的 `.env`**。若按默认部署，HS256 用的就是这个公开字符串——攻击者可用任意 `sub` 自行签发合法 Token，直接以管理员身份登录。

**建议**：
- 启动时强制校验：若 `DEBUG is False` 且 `SECRET_KEY` 仍为默认值/示例值，直接抛错拒绝启动（用 pydantic `field_validator` 即可）。
- `lifespan` 初始化时做一次检查并打印醒目提示。
- 部署文档补充生成命令：`python -c "import secrets; print(secrets.token_urlsafe(32))"`。

### 🟠 C2【High】SQLite 外键级联从未启用，删除员工留下孤儿数据
`backend/app/core/database.py:12-22` 创建引擎时**没有开启 `PRAGMA foreign_keys=ON`**，也没有用 `event.listen(engine, "connect", ...)` 设置。SQLite 只有在连接上显式开启该 PRAGMA 时才会执行 `ON DELETE CASCADE/SET NULL`。而模型里确实声明了级联：
- `models/state_log.py:16` `employee_id = ForeignKey(..., ondelete="CASCADE")`
- `models/employee.py:25` `group_id = ForeignKey(..., ondelete="SET NULL")`

**后果**：删除员工（`api/employees.py` 的删除逻辑）时，该员工的 `EmployeeStateLog` 行**不会被级联删除**，成为永久孤儿数据；`group` 删除之所以"看起来没出事"，是因为 `api/groups.py` 在 API 层手动把 `employee.group_id` 置空——这恰恰说明作者以为级联会生效，实则靠手写兜底。

**建议**（二选一）：
```python
from sqlalchemy import event
@event.listens_for(engine, "connect")
def _fk_pragma(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```
或彻底放弃依赖 DB 级联，在每个删除路径显式清理子表。

### 🟠 C3【High】默认管理员 `admin/admin123` 且永不强制改密
`backend/app/services/init_service.py:25`、`backend/seed.py:93`
```python
admin = Admin(username="admin", hashed_password=hash_password("admin123"))
```
广为人知的弱凭据，且**系统无任何强制首次登录改密逻辑**，也不检测"是否仍为默认密码"。任何未改密的部署都是裸奔。

**建议**：`Admin` 表加 `must_change_password` 字段，登录后未改密则禁止其它操作；或首次启动随机生成密码并仅在日志输出一次。同时移除前端登录框对默认口令的预填（见 H8）。

### 🟠 C4【High】批量导入 / 排序接口 `list[dict]` 零校验，畸形请求直接 500
`api/employees.py:78`、`api/groups.py:64,82`（接收 `body: list[dict]`）
```python
for item in body.items:
    e = db.get(Employee, item["id"])          # 缺 "id" → KeyError → 500
    e.order_id = item["order_id"]             # 非 int 也照写
    int(emp_entry.get("state", 1))            # 传 "on" → ValueError → 500
```
- `item["id"]` 缺键即 `KeyError`。
- `import_groups` 里 `int(state)` 对 `"on"`/非数字抛 `ValueError`。
- `import_groups` 接收任意长度 `list[dict]`，无上限，可造成大 payload DoS。

**建议**：为这些接口定义强类型 Pydantic 模型（如 `ItemSort(id: int, order_id: int | None, group_id: int | None)`），并加数量上限；把 `day_info.py:8` 那种 `pattern` 校验风格推广到批量接口。

### 🟠 C5【High】全部读接口无鉴权，员工 PII / 排班 / 统计完全公开
以下接口均未加 `Depends(get_current_admin)`：
- `GET /api/employees`、`GET /api/groups`
- `GET /api/days`、`GET /api/days/modified`
- `GET /api/schedule/{year}/{month}`、`GET /api/schedule/auto-preview/{year}/{month}`
- `GET /api/stats/*`，含 `/api/stats/employee/{id}`（可枚举任意 id 拉取某人全部值班明细）

员工姓名、分组、值班历史、个人频率均属敏感数据，且个人明细接口可被枚举拖库。

**建议**：至少对 `/stats/employee/{id}`、`/employees`、`/schedule` 加鉴权；若产品决策就是"只读公开"，请在文档中显式记录该风险与前提。

### 🟠 C6【High】`compute_eligible_days` 口径错误：全员"应值班天数"相同且与分子不一致
`backend/app/services/schedule_service.py:168-209`（已逐字核对）
```python
total_by_type = {"workday": 0, "weekend": 0, "holiday": 0}
for d in all_dates:
    ... total_by_type[dt_val] += 1
total = sum(total_by_type.values())
for eid in employee_ids:
    result[eid] = {**total_by_type, "total": total}   # ← 每个人完全一样
```
问题：
1. 它**根本没有判断"该员工当月是否真的值班"**，只是把传入的 `employee_ids` 全部赋上"整月天数"。函数注释自称"简化算法…不再依赖 state_logs 或 group_snapshot"——这意味着 `EmployeeStateLog` 表与快照里的 `state_logs` 在统计口径上**形同死代码**，而该表存在的本意正是处理"某人 7 月 1-15 不值班、16-31 值班 → 有效 16 天"这类场景。
2. 分母（eligible = 整月自然日，含周末/节假日）与分子（duty = 实际排班条目数）**口径不一致**，导致"频率 = eligible / total_duty"含义含糊，且所有员工分母相同，无法体现因请假/入职导致的公平差异——而这通常是排班系统的核心诉求。

**影响**：前端"频率/应值班天数"指标失真，且无法体现个体实际可值班区间。
**建议**：按 `EmployeeStateLog` 真实计算每个员工在 `[start, end]` 内 `state==1` 的天数（按日遍历 + 状态段求交）；或至少在文档中明确"eligible = 区间内自然日总数"并改名避免误导，同时让分子/分母口径一致。

---

## 三、中等问题（Medium）

### 后端
- **M1 / DEBUG 默认 True**（`config.py:16`、`main.py:29-30`）：生产若遗漏 `DEBUG=False`，`/docs`、`/redoc` 暴露，且 500 回显堆栈（含 SQL、路径），便于探测。
- **M2 / 登录无限流、无锁定、无验证码**（`api/auth.py:14-25`）：错误信息不区分用户/密码（这点做得好），但无任何失败次数限制，可被在线爆破。建议加 `slowapi` 限流或对管理员失败计数锁定。
- **M3 / 改密后旧 Token 仍有效**（`core/security.py:31-38`）：JWT 仅有 `sub`+`exp`，无 `jti`/无 `token_version`。`change_password` 后旧 Token 在 7 天 `exp` 内仍可用。**建议**：`Admin` 加 `token_version`，签发时写入、`get_current_admin` 校验，改密自增即让旧 Token 失效。
- **M4 / `Employee.name` 无唯一约束**（`models/employee.py:19`，仅 `String(10)`，无 `unique`）：对比 `Group.name`、`Admin.username` 都有 `unique`，员工姓名在库层面无约束。业务层用 `query().filter(name==).first()` 校验，但**并发可重名**；更关键的是排班 `schedule_json`、统计去重大量依赖姓名（`api/stats.py`），同名会让统计/历史合并出错。**建议**：加 `unique=True` 或 `index=True` + 事务保护；导入也做 DB 级唯一。
- **M5 / 无全局异常处理、无日志**（`services/init_service.py` 仅用 `print()`，全项目无 `logging`）：任何未捕获异常直接 500，生产 `DEBUG=True` 时泄露堆栈。**建议**：配置 `logging` 输出 stdout；注册全局 `Exception` / `RequestValidationError` / `SQLAlchemyError` 处理器，统一返回 `{detail: ...}`。
- **M6 / SQLite 无 `timeout`、无 WAL**（`database.py:18-22`）：未设 `timeout`（默认 5s 写冲突直接报错），未开 WAL，且 `check_same_thread=False` 在 uvicorn 多 worker 下易触发 `database is locked`。**建议**：`connect_args` 加 `{"timeout": 30, "check_same_thread": False}` 并开 WAL；或生产迁移 PostgreSQL（注意 `models/schedule.py` 用了 `sqlalchemy.dialects.sqlite.JSON`，迁 PG 需改为 `sqlalchemy.JSON`）。
- **M7 / `employee_name` 声明 `String(10)` 与真实写入长度严重不符**（`models/state_log.py:19`）：实际写入如 `groups.py` 的 `组更名:第{g.order_id}组「{g.name}」→「{body.name}」`（超 10 字）。SQLite 忽略 VARCHAR 长度"恰好能跑"，但**迁移到 PostgreSQL/MySQL 会直接 `value too long`**——典型"侥幸能跑"的移植炸弹。**建议**：改 `String(255)` 或 `Text`。
- **M8 / `create_group` 的 `max(order_id)+1` 存在读后写竞态**（`api/groups.py:46-47`）；`save_schedule` 的"查-插/更"非原子（`api/schedule.py:232-255`），并发同月保存可能触发 `UniqueConstraint("year","month")` 冲突。

### 前端（高危项合并入此处）
- **M9【High·安全】Token 明文存 localStorage，可被 XSS 窃取**（`src/stores/auth.js:7-8,18-22`）：Token 与管理员信息以明文存于 `localStorage`，任何脚本（含第三方依赖、插件、XSS）都能读取冒用。结合 M11 的注入点，一旦某员工姓名字段被注入脚本，即可在查看者浏览器窃取 `shift_token`。**建议**：改用后端 `httpOnly + Secure + SameSite` Cookie（`axios` 设 `withCredentials: true`）；若必须前端持有，至少缩短有效期并配套刷新令牌。
- **M10【Medium·安全】PDF 导出用 `innerHTML` 注入后端数据，存在存储型 XSS**（`src/views/PersonDuty.vue:447`）：把员工姓名/组名/日期拼进 HTML 字符串后直接 `sDiv.innerHTML = sections[si]` 并插入真实 DOM。若姓名含 `<img src=x onerror=...>` 即执行脚本。注意 `dist/` 里虽有 `purify.es-*.js`，但那是 jsPDF 自带依赖，**应用自身并未使用 DOMPurify**。**建议**：`import('dompurify')` 对动态字段做 `sanitize`，或统一对 `emp.name/group_name` 做 HTML 转义后拼接。
- **M11【Medium·安全】硬编码默认口令并预填到登录框**（`src/layouts/MainLayout.vue:26` 的 `loginForm = reactive({ username:'admin', password:'admin123' })`，模板还明文写出默认口令）：口令写进源码与 `dist/` 产物，属信息泄露，且任何 XSS 都能读到预填口令。**建议**：登录框不预填口令；移除源码/模板中的默认口令提示（与 C3 联动）。
- **M12【Medium】auth store `JSON.parse` 无异常保护，可白屏崩溃**（`src/stores/auth.js:8`）：若 `localStorage.shift_admin` 被改坏或跨版本结构不兼容，`JSON.parse` 抛错使 store 初始化失败，因 `MainLayout` 始终挂载，整个应用白屏。对比 `src/stores/staff.js:9-16` 已用 try/catch，此处不一致。**建议**：try/catch 包裹，失败复位为 `null` 并清除该键。
- **M13【Medium】路由无导航守卫，未做鉴权保护**（`src/router/index.js`：仅有 `afterEach` 设置标题，无 `beforeEach`/`beforeEnter`/`meta.requiresAuth`）：所有页面任何访客都能直接打开 URL 访问，写保护只靠各视图的 `canEdit` + 后端 401 兜底。**建议**：增加全局 `beforeEach` 统一处理登录态与跳转。
- **M14【Medium】401 处理脆弱、可能重复弹窗**（`src/api/http.js:28-43`）：用 `url.includes('/auth/login')` 字符串匹配判断登录接口（路径一调就误判）；多个并行请求同时 401 会触发多次 `logout()` 与多个登录弹窗。**建议**：登录请求由调用处自行 catch（其 401 已由 MainLayout 处理），拦截器只对非登录 401 统一处理；用标记位（如 `auth.isHandling401`）去重。
- **M15【Medium】Stats.vue 与 PersonDuty.vue 大量重复逻辑（~150+ 行）**：`modeOptions`/`periodLabel`、`freqTypes`/`toggleFreqType`/`customFreq`、排序相关 `sortKey`/`toggleSort`/`sortColors`/`sortIconHtml`，以及频率配色数组 `['workday',color:#10b981]`，在两文件模板中各写一遍；`dayTypeOptions`/`dayTypeMap` 还在 `DaySetup.vue`/`ScheduleMake.vue` 反复出现。**建议**：抽 `composables/useStatsFilters.js`（频率/排序）与 `utils/dayType.js`（日期性质常量与映射），两视图共用；或抽 `<SortableTableHeader>` 组件替代 `v-html` 箭头。
- **M16【Medium】人员下拉未虚拟化，百人规模有卡顿风险**（`src/views/PersonDuty.vue:605-631` 的 `el-select` 渲染含已删除者的全部 `allPersons`）：Element Plus 默认 `el-select` 不虚拟滚动。**建议**：改 `el-select-v2`（虚拟列表）或历史人员分页/搜索懒加载。
- **M17【Medium】ECharts 全量打包（1MB 分块）**（`src/views/PersonDuty.vue:4` `import * as echarts from 'echarts'`，`dist/PersonDuty-*.js` 达 1.07 MB）。**建议**：按需引入 `echarts/core` + 所需 charts/components/renderers，主包可显著下降。

---

## 四、低 / 建议（Suggestion）

**后端**
- `bcrypt` 仅取前 72 字节（`security.py:19`）：长中文密码超出部分被静默丢弃，可能让两个不同长密码哈希"相等"。建议接口对密码长度设上限（≤64，与 `AdminLogin.password` 的 `max_length=64` 一致）。
- `get_current_admin` 中 `int(payload["sub"])`（`deps.py:36`）未捕获异常，Token 被伪造时 `int()` 抛 `ValueError` → 500，建议加 try/except 返回 401。
- `ScheduleItemIn.date` 为 `str` 未校验格式（`schemas/schedule.py:22`）：`stats.py` 用字符串比较日期，前传 `"2026/07/01"` 会让排序/过滤全部出错且无报错，建议用 `date` 类型接收后再 `.isoformat()`。
- `change_password` 用裸 `dict` 而非 Schema（`api/auth.py:34`），`new_password` 只校验最小长度 6、无最大长度。
- `compute_statistics` 中 `group_stats`/`by_group` 为死代码（`schedule_service.py:120-121,135-141`）：计算了但返回值只用 `by_employee` 与 `by_day_type`。
- 函数体内 `import` 模型（`groups.py`、`employees.py`、`schedule.py` 多处）——增加阅读成本，建议提到模块顶部。
- `_default_day_type` 在 `api/day_info.py:20` 与 `seed.py:21` 各定义一份，建议抽到 `models/day_info.py`。
- 统计区间过滤用 `year*100+month` 算术（`stats.py`），无法利用 `year/month` 索引，建议元组比较或复合索引。
- 累计/年/自定义统计无缓存（仅月度有 30s TTL），大数据量下每次重复计算。
- 建议用 Alembic 迁移替代 `create_all`（`init_service.py:16`），便于表结构演进。

**前端**
- 全量 JS，无 TypeScript，无编译期类型保护（T1）——排班/统计数据结构复杂，易出字段错位 bug。建议逐步迁移 `<script setup lang="ts">`。
- 多处不必要 `v-html`（`Stats.vue:355-387`、`PersonDuty.vue:807-847` 渲染排序箭头）——内容仅静态字符，风险低但违反安全实践，建议改 `<span>{{ arrow }}</span>` 或小组件。
- 大量空 `catch (e) {}` 静默吞错（`StaffManage.vue`、`ScheduleMake.vue`、`DaySetup.vue` 多处）——如 `saveSchedule` 先 save 成功再 lock，lock 失败被吞会导致前端状态与后端不一致（E1）。
- `onMounted(asyncFn)` 未 `.catch`（`DaySetup.vue:114`、`Stats.vue:132`、`ScheduleMake.vue:151`），网络失败产生未处理 Promise 拒绝（E2）。
- 无环境变量机制，`baseURL` 硬编码 `/api`（`http.js:7`），无 `.env*`——多环境部署不灵活（B1/A2）。建议 `import.meta.env.VITE_API_BASE || '/api'`。
- `html2pdf.js` 声明但未使用（`package.json:21`），PDF 实际用动态 `import('html2canvas')`+`import('jspdf')`——删掉无用依赖（B2）。
- 无 lint/test/typecheck 脚本，仅 dev/build/preview（B3）。
- `tailwind.config.js` 中 `ambery` 与 `slatey` 调色板完全相同（疑似复制粘贴错误），属死配置；多处硬编码 `#1a2a44`、`#409eff` 等主题色未复用 `main.css` 的 `--color-*`。
- `ScheduleMake.vue` 1254 行、`PersonDuty.vue` 929 行、`StaffManage.vue` 972 行等超大组件，建议按职责拆分。
- 潜在空值崩溃：`PersonDuty.vue:906` 的 `row.coworkers.length` 未做可选链，建议 `?.`。

---

## 五、优先修复清单（Top 10）

| # | 问题 | 位置 | 严重度 | 关键动作 |
|---|---|---|---|---|
| 1 | JWT 默认密钥硬编码，Token 可被伪造 | `core/config.py:22` | Critical | 启动校验非默认值；生产拒绝用默认密钥 |
| 2 | SQLite 外键级联未启用，删除员工留孤儿日志 | `core/database.py` | High | `PRAGMA foreign_keys=ON`（event listener） |
| 3 | 默认管理员 `admin/admin123` 不强制改密 | `init_service.py:25` | High | 加 `must_change_password` 或随机密码 |
| 4 | 批量导入/排序 `list[dict]` 零校验 → 500 | `employees.py:78`、`groups.py` | High | 强类型 Pydantic + 数量上限 |
| 5 | 全部读接口无鉴权，PII 暴露 | 各 `api/*.py` GET | High | 至少 `/stats/employee/{id}`、`/employees`、`/schedule` 加鉴权 |
| 6 | `compute_eligible_days` 口径错误，频率失真 | `schedule_service.py:168-209` | High | 按 `EmployeeStateLog` 真实计算各员工可值班天数 |
| 7 | Token 明文存 localStorage，可 XSS 窃取 | `stores/auth.js:7-8` | High | 改 httpOnly Cookie 或加刷新令牌 |
| 8 | PDF 导出 `innerHTML` 注入后端数据 | `PersonDuty.vue:447` | Medium | 引入 DOMPurify 对动态字段 sanitize |
| 9 | 无全局异常处理/日志；SQLite 无 timeout/WAL | `database.py`、`init_service.py` | Medium | logging + 异常处理器 + WAL/timeout |
| 10 | `Employee.name` 无唯一约束；`employee_name` 长度不符 | `models/employee.py:19`、`state_log.py:19` | Medium | 加 unique；改 String(255)/Text |

---

## 六、值得肯定的地方（Positive）

- **README 极为详尽**：技术栈、目录、功能、排班算法、统计口径、安全说明、部署、FAQ 一应俱全，质量远超一般内部项目。
- **ORM 与算法方向正确**：SQLAlchemy 2.0 风格、`generate_schedule` 轮转逻辑清晰、bcrypt + JWT(HS256) 选型合理。
- **`day_info` Schema 校验规范**（`schemas/day_info.py` 用 `pattern` 限制 `day_type`），可作为其它接口的模板。
- **`utils/format.js` 的 `parseDateStr` 实现扎实**：覆盖多种中英文/Excel 序列号格式，且被多视图复用。
- **前端路由全部 `import()` 懒加载**，首屏体积可控；`xlsx/jspdf/html2canvas` 按需懒加载，做得好。
- **业务边界处理细致**：Excel 导入校验、快照冻结历史、频率公式透出、PDF 分页切片，体现对业务的深理解。

---

## 七、建议改进路线（分阶段，不破坏现有功能）

1. **阶段一 · 安全加固（1-2 天）**：C1（密钥校验）、C3（强制改密）、C5（读接口鉴权）、M9（Cookie/刷新）、M10（DOMPurify）、M11（移除预填口令）、M13（路由守卫）。
2. **阶段二 · 数据正确性（2-3 天）**：C2（外键 PRAGMA）、C6（eligible 真实计算）、C4（批量接口强校验）、M4（姓名唯一）、M5（日志+全局异常）、M6（WAL/timeout）。
3. **阶段三 · 可维护性与性能（持续）**：M15（抽取重复逻辑）、M17/T4（ECharts 按需）、M16（虚拟下拉）、补测试（services 纯函数单测 + auth 集成测试）、引入 Alembic、补 `.env` 与环境变量机制。

> 综上：算法与 ORM 用法大体正确，但"安全默认值 + 数据完整性 + 输入边界 + 统计正确性"四块各有一个会直接导致事故或错误结论的硬伤。建议按上表 **1→10** 顺序推进，并尽快补齐测试与日志。
