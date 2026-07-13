# 隔壁小王爱值班

一个简洁的值班排班管理系统：编组 → 日期设置 → 排班 → 分类统计 → 个人查询。

## 技术栈

- **后端**：FastAPI + SQLAlchemy + SQLite + JWT
- **前端**：Vue3 + Vite + Pinia + Vue Router + Element Plus + Tailwind CSS + ECharts
- **PDF 导出**：html2pdf.js（前端生成，无需后端支持）

## 项目结构

```
shiftschedule_pro/
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── api/              # 路由层（auth/groups/employees/day_info/schedule/stats）
│   │   ├── core/             # 配置、数据库、安全、依赖
│   │   ├── models/           # SQLAlchemy 模型
│   │   ├── schemas/          # Pydantic Schema
│   │   ├── services/         # 业务逻辑（排班算法、统计、eligible 计算）
│   │   └── main.py           # FastAPI 入口
│   ├── seed.py               # 测试数据生成（含 3 个月排班样本）
│   └── requirements.txt
└── frontend/                 # Vue3 前端
    ├── src/
    │   ├── api/              # Axios 封装
    │   ├── layouts/          # 主布局
    │   ├── router/           # 路由
    │   ├── stores/           # Pinia 状态
    │   ├── views/            # 页面（人员、日期、排班、统计、个人查询）
    │   └── assets/main.css   # 全局样式
    └── package.json
```

## 快速开始

### 1. 启动后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

首次启动会自动：
- 创建 SQLite 数据库 `shiftschedule.db`
- 创建默认管理员账号：**admin / admin123**

访问 http://127.0.0.1:8000/docs 查看 API 文档。

### 2. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 ，使用 admin / admin123 登录。

### 3. 生成测试数据（可选）

```bash
cd backend
python seed.py
```

自动生成 28 个组、59 名员工、最近 3 个月的日期信息和排班数据，方便直接测试统计和查询功能。

## 功能说明

### 1. 人员管理 (`/staff`)

- 创建值班组，拖拽调整组顺序
- 新增/编辑/删除员工，支持按组筛选和姓名搜索
- 切换员工值班状态（值班中 / 不值班）
- 删除组时组员不会被删除，自动移入"未分组"
- 批量导入人员（支持 Excel 模板下载）
  - 追加模式：禁止重名，需手动重命名
  - 覆盖模式：清空后重新导入
- 导出当前人员列表到 Excel

### 2. 日期设置 (`/days`)

- 月历视图，自动初始化当月所有日期
- 默认按周几判断工作日/周末
- 点击或框选日期，批量设置为节假日/调休日
- 实时显示当月各性质天数统计
- 修改的日期以琥珀色边框标记，支持筛选查看
- 批量导入日期（支持跨月，支持多种日期格式）
- **已保存排班的月份日期属性冻结**，不可修改（需先删除排班解锁）

### 3. 排班 (`/schedule`)

- 选择起始组和需排班的日期性质
- 一键生成轮转排班预览（按组顺序循环）
- 日历视图支持手动调整某天的值班组
- 保存排班（按月覆盖式存储，自动保存组/员工快照）
- 排班锁定/解锁（锁定后禁止修改）
- 排班导入/导出
  - 仅限当月，必须包含当月所有天
  - 严格验证组和人员必须与当前数据完全一致
  - 模板预填当月所有日期，含示例数据
  - 重复日期自动拒绝

### 4. 统计 (`/stats`)

- 三种统计模式：**按月 / 按年 / 累计**
- 员工明细表：工作日/周末/节假日值班天数、合计、应值班天数
- 自定义频率计算：勾选参与计算的日期性质（工作日/周末/节假日）
- 频率值下方显示计算公式（如"23天可值 / 12天值班"）
- 表格列支持点击排序，统一配色方案
- 导出 Excel 报告

### 5. 个人查询 (`/person`)

- 可搜索人员下拉框（支持 100+ 人员，包括已删除但有值班记录的人员）
- 三种统计模式：按月 / 按年 / 累计（与统计页一致）
- 6 张概览卡片：累计值班、应值班天数、工作日/周末/节假日/综合频率
- 每张频率卡片下方显示计算公式
- 月度值班趋势折线图
- 日期性质分布饼图
- 月度频率明细表（支持排序，配色与统计页统一）
- 所有值班记录表：日期可排序、性质可筛选、分页显示（20 条/页）
- **导出 PDF 数据报告**：包含基本信息、概览统计、图表、月度明细表、值班记录表

## 数据模型

| 模型 | 说明 |
|------|------|
| `Admin` | 管理员账号（仅一个） |
| `ShiftGroup` | 值班组（含 order_id 决定轮转顺序） |
| `Employee` | 员工（属于一个组，state=1 参与值班） |
| `DayInfo` | 每日信息（day_type: workday/weekend/holiday/vacation） |
| `Schedule` | 月度排班记录（JSON 存储，含 group_snapshot 快照） |
| `EmployeeStateLog` | 员工状态变更日志（用于 eligible 天数计算） |

## 排班算法

```
按 ShiftGroup.order_id 排序得到组序列 G[0], G[1], ..., G[n]
从 start_group 开始，依次为每个待排日期分配一个组：
  第 0 天 → G[start_index]
  第 1 天 → G[(start_index + 1) % n]
  第 2 天 → G[(start_index + 2) % n]
  ...
```

简单可预测，不参与值班的员工（state=0）不会出现在排班中。

## 统计与 eligible 天数计算

- **eligible 天数**：员工在统计区间内处于值班状态（state=1）的天数，按日期性质拆分
- 每月排班保存时自动生成 `group_snapshot`（组/员工/状态日志快照），确保历史统计不受后续人员变动影响
- 状态日志中 `old_state == new_state` 的记录会被过滤（如组变更、导入日志），避免错误影响计算
- 统计模式固定为按月/按年/累计，日期边界始终对齐月初/月末，确保计算准确

## 安全说明

- 默认密码 `admin123` 仅用于初次登录，登录后请立即在右上角修改密码
- JWT 密钥在 `app/core/config.py` 中，生产环境请通过环境变量覆盖
- 所有写操作（POST/PUT/DELETE）API 均有 `Depends(get_current_admin)` 认证保护
- 生产环境设置 `DEBUG=False` 关闭 API 文档（/docs, /redoc）
- CORS 默认仅允许 `localhost:5173`，部署时需调整

## 生产部署

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEBUG` | 调试模式（True 开启 /docs，False 关闭） | `True` |
| `DATABASE_URL` | 数据库连接（默认 SQLite） | `sqlite:///./shiftschedule.db` |
| `JWT_SECRET` | JWT 签名密钥 | 内置默认值 |
| `CORS_ORIGINS` | 允许的前端源 | `http://localhost:5173` |

### 部署方式

```bash
# 传统服务器
cd backend
echo "DEBUG=False" > .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端构建
cd frontend
npm run build
# 将 dist/ 部署到 Nginx 或其他静态服务器
```

## 常见问题

**Q: PowerShell 终端中文显示为 `??`？**
A: 这是 PowerShell 终端编码问题，数据库存储和 API 返回的中文是正确的。在前端浏览器中显示正常。

**Q: 32 位 Python 安装依赖失败？**
A: 本项目已避免使用 cryptography/greenlet 等需要 C 编译的包。如果遇到问题，参考 `requirements.txt` 中的注释。

**Q: 已保存排班的月份无法修改日期属性？**
A: 这是设计行为。已保存排班的月份日期属性会被冻结，防止历史统计失真。需先删除该月排班才能解锁修改。

**Q: 删除员工后还能查询其历史值班记录吗？**
A: 可以。个人查询页的人员列表包含已删除但有值班记录的人员，选中后即可查看其历史数据。
