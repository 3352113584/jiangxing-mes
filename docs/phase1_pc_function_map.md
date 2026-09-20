# 匠星智造 MES — PC 端 Phase 1《功能地图》（统一版）

> **文档性质**：功能地图（Function Map）。**不是代码、不是接口契约、不是业务规则变更书**。
> 仅描述"PC 端到底要做什么"——模块、页面、角色、查询、字段、操作、跳转、与构件/手机端/实体的关系。
> **不写前端代码、不写后端代码、不新增 Migration、不改 ORM/DB、不改 V1.2 冻结规则、不实现新计价逻辑、不实现 `labor_pricing_condition`。**

---

## 0. 边界与术语对齐

### 0.1 依据基线

| 项 | 值 |
|---|---|
| V1.2 冻结基线 commit | `7345d66`（docs/arch: freeze MES V1.2 baseline） |
| Alembic head | `c8e2f3a4b5c6`（单 head） |
| 权威业务规则 | `docs/v1.2_business_decisions_v2.md`（唯一权威速查）+ `v1.2_database_domain_model.md` |
| PC 现状 | 仓库 `frontend/` 仅有 `Dockerfile`+`.gitkeep`，**PC 前端源码尚不存在**（F6 状态待建工程） |
| 后端 API | 仅 11 个端点（auth×2、tasks×4、android×2、history×1、health×1） |

### 0.2 术语对齐（**旧命名 → 冻结模型真实实体**，仅记录冲突，不改 V1.2）

| 本功能地图沿用（冻结模型） | 用户指令/旧资料里的命名 | 说明 |
|---|---|---|
| `prod.production_task`（生产任务，身份=构件×工序步骤×attempt，单一 `execute_team_id`） | "component_processes"（主表，按构件+工序+项目唯一） | **冻结模型无 `component_processes` 表**（全局 grep 0 命中）。生产登记主表在 V1.2 即 `production_task`。 |
| `prod.production_report` + `_worker` + `_measure`（报工事实，append-only） | "process_register_logs"（流水） | 冻结模型无 `process_register_logs` 表；流水级登记由 `production_report` 及其子表承担。 |
| `eng.route_template_step`（工序身份锚点：step_no + operation_type_id） | "工序" | 工序字典为 `ref.operation_type`（16 条 seed）；项目内工序身份锚定在 `route_template_step`。 |

> ⚠️ **冲突登记（不修改）**：用户指令业务链里的 `component_processes`/`process_register_logs` 与冻结 V1.2 实体名不一致。本功能地图一律以冻结模型实体名为准；如需保留旧名作为 UI 展示别名，须待业务确认，不得据此改库。

### 0.3 状态图例

| 标记 | 含义 |
|---|---|
| 🟢 已有后端支持 | 有可用 API 且服务/测试已具备 |
| 🟡 数据齐 / 缺 API | 表与模型已冻结存在，但缺 API（本 Phase 1 绝大多数页面属此） |
| 🔴 模型/实体缺位 | V1.2 中尚不存在，需先执行迁移/补模型 |
| ⚪ ERP/外部预留 | V1 明确不做，仅留接口 |

### 0.4 与手机端（Android APK）的分工边界（冻结）

- **手机端做**：打卡、构件工序**报工**（`/api/android/register`）、设备报修。
- **PC 端做**：管理/配置/查看/派工/驾驶舱/计价试算/质量检验录入/仓储/装托发运操作/系统配置。
- 同一业务对象（构件、任务、工序）在两端共享同一后端事实；PC 是"管控+查看"，手机是"现场采集"。

---

## 1. 一级模块清单（校验用户列出的 14 项）

以下 14 个一级模块**全部纳入 Phase 1 功能地图范围**（即"PC 端要做什么"的完整画法）。状态为该模块在冻结基线下的后端就绪度。

| # | 一级模块 | 对应 V1.2 域 | 状态 | 合理性判定 | 说明 |
|---|---|---|---|---|---|
| 1 | 老板驾驶舱 | 跨域聚合（只读视图） | 🟡 | ✅ 合理 | 指标事实源齐全，仅缺聚合 API；先落地 A 档指标 |
| 2 | 项目管理 | `md.main_project`/`subproject` | 🟡 | ✅ 合理 | 含子项目；创建/导入 Phase 1 可仅只读 |
| 3 | 构件管理 | `prod.component_list_item`/`actual_component` | 🟡 | ✅ 合理 | 清单导入是项目启动第一步刚需（🟡，服务缺位） |
| 4 | 工艺/工序 | `ref.operation_type`/`eng.route_template`/`project_operation` | 🟡 | ✅ 合理 | 阶段 1 **仅标准工序、不开放自定义工序入口**（NEW-11） |
| 5 | 生产计划 | `prod.production_plan`(+_version/_line) | 🟡 | ✅ 合理 | 表齐，无 API、无计划数据；六指标后置 |
| 6 | 生产任务 | `prod.production_task` | 🟢 | ✅ 合理 | 唯一已有真实 API 的派工闭环（分配/列表/调整/履历） |
| 7 | 生产登记 | `prod.production_report`(+_worker/_measure) | 🟢/🟡 | ✅ 合理 | 报工服务就绪（服务终端无关），PC 以查看/补录为主 |
| 8 | 质量管理 | `prod.quality_inspection`/`ncr`/`rework_order`/`final_qualification` | 🟡 | ✅ 合理 | 表齐；**写入口为零（待补）**，列为冲突 #5 |
| 9 | 班组/人员 | `md.team`/`employee`/`team_operation_capability`/`employee_occupation` | 🟡 | ✅ 合理 | 表齐；权限表未 seed、无鉴权逻辑（冲突 #8） |
| 10 | 劳务计价 | `eng.labor_pricing_rule`(+_version/_condition)/`project_operation_price` | 🟡 | ✅ 合理 | M7 计价链已落地 + 成本试算视图存在；仅供**试算/只读**，非财务核算 |
| 11 | 托盘/包装 | `ship.pallet`(+_load/_history/_weight) | 🟡 | ✅ 合理 | 表齐；操作 API 缺 |
| 12 | 集装箱/发运 | `ship.shipping_container`/`shipment`/`shipment_pallet` | 🔴/🟡 | ⚠️ 需前置 | **`ship.shipment_pallet`（M-P4-2）未执行**，托盘级发运 DB 暂无法承载（冲突 #4） |
| 13 | 设备管理 | `prod.equipment`(+_event/_impact) | 🟡 | ✅ 合理 | 台账/维修/影响链；报修入口在手机端 |
| 14 | 系统管理 | `ref.*`/`aud.*`/`md.permission` 等 | 🟡 | ✅ 合理 | 字典/配置/审计/异常/更正；权限矩阵待定稿 |

> **结论**：14 个模块均合理纳入。第 12 项（集装箱/发运）需先执行 M-P4-2 才能在 DB 层闭环，列为开发顺序末段前置。

---

## 2. 逐模块功能地图

> 每个模块两张表：
> **表 A** = 页面 / 目的 / 查询条件 / 核心列表字段 / 操作（增·改·查·作废）
> **表 B** = 页面 / 跳转关系 / 与实际构件关系 / 与手机端关系 / 涉及 V1.2 实体

---

### 2.1 老板驾驶舱（模块 1）

**使用角色**：老板/厂长、生产/项目管理人员（只读为主）。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 驾驶舱首页 | 一屏关键经营数字 + 风险榜 + 下钻入口 | 时间范围、主项目筛选 | 项目数/在产/构件完成率/本周完成/逾期任务/未闭环异常/故障设备/待检件 | — | — | ✅ | — |
| 风险详情下钻 | 某风险构件的任务/人/料/设备明细 | 风险类型、对象 | 滞后主/子项目、风险班组、材料/设备/质量返工风险清单 | — | — | ✅ | — |
| 归因链下钻 | "为什么落后"→任务→人→设备→料→缺陷单 | 构件/任务 | 影响链节点 | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 驾驶舱首页 | → 项目列表 / 任务列表 / 构件详情 / 异常中心 | 经 `actual_component.production_status`/`quality_status` 聚合 | 数据同源（报工来自手机端） | `md.main_project`、`prod.actual_component`、`prod.production_task`、`prod.production_report`、`ship.*`、`prod.equipment`、`aud.*` |
| 风险/归因下钻 | → 对应模块详情页 | 落到具体构件/任务 | 同源 | 同上 + `aud.exception_impact`、`prod.equipment_impact` |

> **口径纪律**：驾驶舱指标必须同源（全公司唯一事实源）；"生产完成"与"质量合格完成"双口径**分列不合并**（G-2 冻结：`production_completed` 仅由 painting 触发）；成本/计件金额上驾驶舱**待业务确认**（V1 不做财务核算）。

---

### 2.2 项目管理（模块 2）

**使用角色**：项目经理、生产管理人员、老板。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 项目列表 | 浏览主项目 | 状态（八态）、交期段、关键字 | 项目编号/名称/客户/状态/交期/子项目数/构件完成率/质量摘要/风险 | —（API 缺） | — | ✅ | — |
| 项目详情（多 Tab T1~T13） | 单项目全维查看 | 项目 ID | T1 概况/T2 子项目/T3 构件清单/T4 进度/T5 质量/T6 计划/T7 装托/T8 发运/T9 材料/T10 图纸/T11 异常/T12 审计/T13 报表 | — | — | ✅ | — |
| 子项目详情 | 子项目独立业务单元 | 子项目 ID | 类型、状态、构件数、进度 | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 项目列表 | → 项目详情 → 子项目/构件/任务/驾驶舱 | 经 `subproject→actual_component` 上溯 | 无直接写 | `md.main_project`、`md.subproject`、`aud.project_status_history` |
| 项目详情 T3 构件清单 | → 构件管理 | 1 主项目含 N 子项目含 N 构件 | 无 | `prod.component_list_item`、`prod.actual_component` |
| 项目详情 T4 进度 | → 生产任务/生产登记 | 逐构件 | 手机报工驱动进度 | `prod.production_task`、`prod.production_report` |

> **阶段 1 范围**：创建项目/导入项目/编辑项目属 🔴 缺 API，本 Phase 1 先**只读**；如工厂要求 PC 建项目，需新增 API（不在冻结范围，待授权）。

---

### 2.3 构件管理（模块 3）

**使用角色**：项目文员、生产/质量管理人员。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 构件清单（按子项目） | 清单行浏览 | 子项目、构件号、材质、状态 | 构件号/规格/理论单重/清单数量/实例数/状态 | — | — | ✅ | — |
| 清单导入 | Excel/CSV 导入 | 批次、文件 | 导入批次/映射版本/行状态（成功/失败） | ✅（🟡 服务缺位） | — | ✅ | 批次撤回 |
| 构件台账/详情 | 实际构件检索 | 构件号/序列/状态/重量 | 构件号/QR/生产状态(10值)/质量状态(6值)/主责班组 | — | — | ✅ | — |
| 构件履历时间线 | 单构件全生命周期 | 构件 ID | 事件/报工/检验/装载/发运节点 | — | — | ✅ | — |
| 二维码/标签打印 | 构件码生成打印 | 构件 ID | 码值、打印历史 | ✅（打印） | — | ✅ | — |
| 报废登记 | 报废事实 | 构件 ID | 原因/时间/批准；序号不释放 | ✅ | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 构件清单 | → 构件详情 → 生产任务/质量/装托 | **核心**：`component_list_item`（多件源头）→ `actual_component`（一件一行，隐含数量 1，无 quantity 列） | 手机报工按构件号扫码 | `prod.component_list_item`、`prod.actual_component`、`prod.qr_code_registry`、`imp.*` |
| 构件详情履历 | → 各业务模块 | 1 构件 1 实体 | 同源 | `prod.actual_component_event`、`prod.component_scrap_record` |

> **铁律**：`actual_component` 永远隐含数量 1、禁止 quantity 列；多件由 `component_list_item.quantity` 展开 N 行 actual_component（RED-01）。清单导入为项目启动第一步最高频刚需，但其 `imp.*` 服务层完全缺位（NEW-10），工作量最大。

---

### 2.4 工艺/工序（模块 4）

**使用角色**：工艺/生产工程师、生产管理人员（配置类，阶段 1 以查看为主）。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 工序字典 | 标准工序查阅 | 是否关键/可计件 | operation_type 16 条：code/name/is_critical/is_countable/sort_no | —（阶段1 不开放自定义入口） | — | ✅ | — |
| 标准工序模板 | 构件类型→工序模板 | 构件类型 | component_type_process_template 版本/状态 | — | — | ✅ | — |
| 项目工艺路线 | 子项目级路线 | 子项目/主项目 | route_template + route_template_step（step_no×operation_type_id） | — | — | ✅ | — |
| 项目工序价格 | 项目价版本 | 项目工序 | project_operation（operation_type_id XOR custom_name）、project_operation_price 版本/单价/price_basis | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 标准工序模板 | → 项目工艺路线（采用/复制） | 经 `component_type_dict` 沉淀工序 | 无关 | `ref.component_type_dict`、`eng.component_type_process_template`、`eng.component_type_process_step` |
| 项目工艺路线 | → 生产任务/生产计划 | 路线步骤=任务/计划行工序身份锚点 | 无关 | `eng.route_template`（含 standard_template_id/_version/adopted_by/at）、`eng.route_template_step` |
| 项目工序价格 | → 劳务计价（M7 优先级1） | 经 project_operation 上溯项目 | 无关 | `eng.project_operation`、`eng.project_operation_price` |

> **纪律**：阶段 1 **仅标准工序**，自定义工序入口排除（NEW-11）；`route_template` 挂子项目级（H-5 方案 A，`subproject_id` 可空）。`team_operation`（班组可执行工序）表尚未建，PC 阶段 1 不展示该列（避免永久空列）。

---

### 2.5 生产计划（模块 5）

**使用角色**：计划员、生产主管。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 计划编制 | 月/周/日计划头+行 | 子项目、周期类型 | production_plan（status: draft/approved/frozen）、plan_line（构件×工序步骤） | ✅（🟡 API 缺） | ✅ | ✅ | 版本冻结 |
| 计划版本与调整 | 版本对比/调整留痕 | 计划 ID | 原/新目标、原因、人、时间 | ✅ | ✅ | ✅ | — |
| 六指标与偏差 | P-14 健康度 | 计划 ID | 计划总量/应完成/实际/差额/完成率/风险态 | — | — | ✅（依赖计划数据） | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 计划编制 | → 生产任务（下达） | 计划行粒度=actual_component×route_template_step | 无关 | `prod.production_plan`、`_version`、`_line`、`plan_adjustment` |
| 六指标 | → 驾驶舱（健康度升级） | 经计划行聚合 | 无关 | `aud.plan_progress_snapshot` |

> **后置**：六指标（P-14）需计划数据先有内容 + 应完成节奏算法 + 风险阈值初值；排在驾驶舱 A 档之后。

---

### 2.6 生产任务（模块 6）

**使用角色**：生产调度/班长（PC 派工）、班组成员（手机接单）。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 任务分配 | 派工（均衡/手动） | 子项目 + 工序步骤 | 待分配构件集、候选班组 | — | ✅（分配） | ✅ | — |
| 任务列表 | 任务浏览 | 项目/子项目/工序/工序类型/班组/状态 | actual_component×step×attempt、execute_team_id、status、planned_end | — | — | ✅（🟢 已有 `/api/tasks`，待补分页/鉴权） | — |
| 任务调整 | 改执行班组 | 任务 ID | 当前/新班组 | — | ✅（reassign，已有履历则拒 409） | ✅ | 取消（主管权限） |
| 班组执行看板 | 班组任务量/完成量（执行口径） | 班组/周期 | 执行口径工作量（P-12 双口径显式标注） | — | — | ✅（🟡 API 缺） | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 任务分配 | → 任务列表 → 生产登记 | 直接针对 actual_component×step | 手机"我的任务"同源 | `prod.production_task`、`prod.task_participant` |
| 任务列表 | → 构件详情/履历 | 1 构件多任务（每 step 一行，可不同班组） | 手机报工写 execute_team_id | `prod.production_task`、`prod.primary_team_assignment` |

> **铁律**：生产任务按团队分发（横向承包，每班组做多道工序，每团队管多项目）；单一 `execute_team_id`（一个任务一个执行班组）；主责 `primary_team_assignment` 与执行分离；多班组真相靠多条任务/报工行，非单表 team_id。派工班组下拉**不过滤** `team_operation`（D-2：负责≠只能执行）。

---

### 2.7 生产登记（模块 7）

**使用角色**：班组成员（手机报工）、PC 文员（补录/查看）。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 生产报工（手机入口） | 构件工序登记 | 构件号/工序/班组 | 报工事实（task_id、operation_snapshot、execute_team_id 快照、channel、occurred_at） | ✅（手机 `/api/android/register`，服务就绪） | — | ✅ | 冲正（窄路径） |
| 生产履历（PC 查看） | 登记结果查询 | 项目/班组/工序/日期/构件 | production_report 列表（分页≤200） | — | — | ✅（🟢 `/api/production-reports`，待补鉴权） | — |
| 工序状态矩阵 | 工序×状态计数 | 子项目 | 各工序在制/完成件数 | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 生产报工 | ← 手机端采集；→ 生产任务/履历/质量 | 报工绑定 actual_component×step | **手机端主力写入**，PC 只读/补录 | `prod.production_report`、`_worker`、`_measure` |
| 生产履历 | → 构件详情/质量/驾驶舱 | 1 构件 N 报工 | 同源 | `prod.production_report` |

> **术语**：本模块即用户链中的"生产登记"，冻结模型对应 `production_report`（旧名 `process_register_logs` 不存在）。`operation_snapshot` 为工序显示名快照，P7 无需 JOIN 工序表（NEW-11 爆炸半径更小）。

---

### 2.8 质量管理（模块 8）

**使用角色**：质检员、生产/质量主管。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 报验/检验登记 | 检验录入 | 构件/检验类型 | quality_inspection（尺寸/首件/成品检/探伤预留，attempt 只追加） | ✅（🟡 API 缺） | — | ✅ | — |
| 不合格与缺陷 | 缺陷/NCR | 检验 ID | quality_defect、ncr（一检多缺陷） | ✅（🟡） | — | ✅ | — |
| 返工管理 | 返工单 | 任务/构件 | rework_order（responsibility_kind 四态、chargeability 三值、reason_category） | ✅（🟡） | — | ✅ | — |
| 最终放行 | 发运前置 | 构件 | final_qualification（RED-09 发运前置） | ✅（🟡） | — | ✅ | 撤销（受控） |
| 质量统计 | 一次/最终合格率 | 项目/周期 | 质量状态(6值)分布 | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 报验/检验 | → 返工/最终放行 | 直接针对 actual_component | 无关（PC 录入） | `prod.quality_inspection`、`ref.inspection_type` |
| 返工管理 | → 生产任务（新 attempt） | 触发 rework_of_task_id | 无关 | `prod.rework_order` |
| 最终放行 | → 发运（RED-09 前置） | 构件级放行事实 | 无关 | `prod.final_qualification` |

> ⚠️ **冲突 #5**：现有质量/返工表与触发器齐全，但**写入口为零**（无 API、无录入页逻辑），属 RED-C2/RED-B2。功能地图按要求画出页面，但是否在 Phase 1 实现写入口，须待业务确认（不自行扩大）。

---

### 2.9 班组/人员（模块 9）

**使用角色**：人事/班组长、系统管理员。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 员工档案 | 人员管理 | 姓名/班组/职业 | employee、occupation（M:N） | ✅（🟡 API 缺） | ✅ | ✅ | — |
| 班组管理 | 班组维护 | team_type | team（production/install/outsource/other，DB 实测 4 值） | ✅（🟡） | ✅ | ✅ | — |
| 班组归属/借调 | 归属史 | 员工/班组 | team_membership（主属当前唯一）、secondment_record | ✅ | ✅ | ✅ | — |
| 主责班组指派 | 构件主责 | 构件/班组 | primary_team_assignment + 变更史 | ✅ | ✅ | ✅ | — |
| 账号与角色 | 用户/角色（🟡 权限未定稿） | 账号/角色 | user_account、role（9 个 seed）、user_role | ✅ | ✅ | ✅ | — |
| 工作量统计 | 执行/主责双口径 | 班组/周期 | 工作量（页面显式标注口径，P-12） | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 班组管理 | → 任务分配（选班组） | 经 task.execute_team_id | 员工账号→手机登录 | `md.team`、`md.team_membership`、`md.employee`、`md.team_leader_history` |
| 主责班组指派 | → 构件详情/任务 | 构件主责 | 无关 | `prod.primary_team_assignment`、`_history` |
| 账号与角色 | → 系统管理(权限) | 无关 | 登录态共享 | `user_account`、`role`、`md.permission`、`role_permission`、`data_scope_policy` |

> ⚠️ **冲突 #8**：`md.permission`/`role_permission`/`data_scope_policy`/`segregation_rule` **有表无逻辑且未 seed**；全仓无 `require_role` 校验；3 个读接口无鉴权（NEW-3/4）。阶段 1 仅"登录+get_current_user"，不做菜单隐藏；"按角色显隐"只能先占位，待 N-27 定稿。员工职业为 M:N（`employee_occupation`+字典），非单值。

---

### 2.10 劳务计价（模块 10）

**使用角色**：生产/项目管理人员、老板（看试算金额）。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 计价规则查看 | 基础价/项目价规则 | 构件类型/工序/班组 | labor_pricing_rule（维度键）、_version（当前生效单价）、project_operation_price（项目价版本） | —（配置留待后续） | — | ✅ | — |
| 工序级劳务计价试算 | 单工序结算试算 | 构件/工序/班组/项目 | M7 优先级：项目价 > 基础价 > MISSING_PRICE | — | — | ✅（🟡 视图+服务就绪，路由缺） | — |
| 成本试算 | 项目/班组/月维度 | 项目/班组/周期 | v_operation_cost_trial / v_project_production_cost 聚合 | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 计价规则查看 | → 劳务计价试算 | 经 project_operation/component_type | 无关 | `eng.labor_pricing_rule`、`_version`、`_condition`、`eng.project_operation_price` |
| 计价试算 | → 驾驶舱（金额卡，待确认） | 经 task→actual_component 聚合 | 无关 | 同上 + 视图 `eng.v_operation_cost_trial`、`eng.v_project_production_cost` |

> **纪律（冻结）**：M7 链 `project_operation_price`(当前版) > `labor_pricing_rule×_version`(当前生效) > **MISSING_PRICE（绝不 0 兜底）**。`labor_pricing_condition` **已入模型但当前未接入计价链**（R7 ORANGE-1），UI **不得**展示"已按条件计价"。计价定性为"劳务费试算/工序级计件劳务费"，**非财务成本核算，不替代 ERP**（§八口径）。

---

### 2.11 托盘/包装（模块 11）

**使用角色**：仓储/发运员、生产管理人员。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 托盘台账 | 托盘资产 | 托盘号/状态 | pallet（空/在用/已装/在箱）、承重 | ✅（🟡 API 缺） | ✅ | ✅ | — |
| 装托作业 | 加托/移托 | 构件/托盘 | pallet_load（is_current）、超重告警 | ✅（装/卸） | — | ✅ | 移托（事件） |
| 装托历史 | 装载流水 | 托盘/构件 | pallet_load_history | — | — | ✅ | — |
| 称重记录 | 托盘称重 | 托盘 | pallet_weight_record（超重硬拦） | ✅ | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 装托作业 | → 集装箱/发运 | 直接装载 actual_component | 无关（PC 操作） | `ship.pallet`、`ship.pallet_load`、`_history`、`_weight_record` |

> 装托=构件进托盘；状态机 `empty→in_use→loaded→in_container→empty`；repack 是事件非状态。PC 为操作主体。

---

### 2.12 集装箱/发运（模块 12）

**使用角色**：发运员、仓库主管、项目经理。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 发运草稿/清单 | 以托盘为操作单位 | 主项目/状态 | shipment（draft）+ shipment_pallet（草稿加入） | ✅（加托入草稿，🟡 依赖 M-P4-2） | — | ✅ | 草稿移除 |
| 装柜作业 | 装柜/卸柜 | 集装箱/托盘 | container_load（is_current） | ✅（装/卸） | — | ✅ | 重装 |
| 集装箱台账 | 柜号/柜型/状态 | 箱号 | shipping_container（空/装货中/已封/已发运/已退运） | ✅（🟡） | ✅ | ✅ | — |
| 发运确认 | 原子五步确认 | 发运单 | 生成 shipment_snapshot 冻结 + 缓存位联动 | ✅（确认） | — | ✅ | 退运/补发 |
| 混装授权 | 跨主项目混托 | 授权人 | mixed_load_authorization | ✅ | ✅ | ✅ | — |
| 到货签收 | 现场签收 | 发运单 | site_delivery_record | ✅（🟡） | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 发运草稿 | → 装柜 → 发运确认 | 经 pallet_load(is_current) 上溯 actual_component | 无关（PC 操作） | `ship.shipment`、`ship.shipment_pallet`、`ship.shipment_snapshot` |
| 发运确认 | → 集装箱台账/到货 | 构件级冻结副本（项目/子项目/托盘号/柜号/重量/QR） | 无关 | `ship.shipping_container`、`container_load`、`shipment_event` |

> 🔴 **冲突 #4（前置阻塞）**：承载实体 `ship.shipment_pallet`（Q5=A 裁决，托盘=发运操作单位）**M-P4-2 迁移未执行 → DB 中不存在**，托盘级发运归属目前无法表达。在 M-P4-2 落地前，发运只能以 `shipment` 主行 + `shipment_snapshot` 表达"已确认发运"，无法做"按托盘加入草稿"。功能地图照画，但**开发需排在 M-P4-2 之后**。封条（container_seal）第一阶段不建表（Q6）。发运前置仅 `final_qualification` 有效事实（RED-09）。

---

### 2.13 设备管理（模块 13）

**使用角色**：设备管理员、生产主管。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 设备台账 | 设备档案 | 类型/状态/关键设备 | equipment（编号/名称/状态） | ✅（🟡 API 缺） | ✅ | ✅ | — |
| 开停机与故障 | 事件记录 | 设备/时段 | equipment_event（运行/停机/故障/维修） | ✅ | ✅ | ✅ | — |
| 维修记录 | 维修闭环 | 设备/事件 | 维修事件与结论 | ✅ | ✅ | ✅ | — |
| 影响链 | 设备→任务→构件 | 设备 | equipment_impact | — | — | ✅ | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 设备台账/事件 | → 生产任务/构件（影响链） | 经 task 上溯构件/班组/计划 | **设备报修入口在手机端（R-DEV-1）**；PC 管台账/维修/影响 | `prod.equipment`、`equipment_event`、`equipment_impact` |

---

### 2.14 系统管理（模块 14）

**使用角色**：系统管理员、审计员。

**表 A**

| 页面 | 目的 | 查询条件 | 核心列表字段 | 增 | 改 | 查 | 作废 |
|---|---|---|---|---|---|---|---|
| 字典维护 | ref.* 字典 | 字典类型 | operation_type/inspection_type/异常七类/子项目类型/构件类型/特征/原因/计量单位 | —（C 类封闭字典，阶段1 不开放改） | — | ✅ | — |
| 编号规则/系统开关 | 配置 | — | code_rule（12 seed）、system_config（4 seed） | — | ✅（受控） | ✅ | — |
| 审计日志 | 操作留痕 | 时间/对象/人 | operation_log、project_status_history | — | — | ✅ | — |
| 异常中心 | 异常处理 | 状态/严重度 | exception_event + impact + handling | — | ✅（处理） | ✅ | — |
| 更正/冲销 | 事实保护 | 状态 | correction_request/approval/entry、reversal_record | ✅（申请） | ✅（审核） | ✅ | — |
| 审批记录 | 审批流 | — | approval_record | — | — | ✅ | — |
| 消息通知 | 系统内消息 | 用户 | notification_message（🚫 不做短信/微信/邮件） | — | — | ✅ | — |
| 权限矩阵配置 | 角色/权限/数据范围 | 角色 | permission/role_permission/data_scope_policy | —（🟡 待 N-27 定稿+seed） | — | ✅（占位） | — |

**表 B**

| 页面 | 跳转关系 | 与实际构件关系 | 与手机端关系 | 涉及 V1.2 实体 |
|---|---|---|---|---|
| 字典维护 | → 各业务模块取数 | 经 ref.* 字典 | 共享字典 | `ref.*`（13 字典表） |
| 审计/异常/更正 | → 各业务模块溯源 | 经审计外键 | 同源 | `aud.operation_log`、`aud.exception_*`、`aud.correction_*`、`aud.approval_record` |

> **枚举中文映射**：22 个 PG ENUM 全英文、13 张 ref 字典为权威中文来源；PC 端中文显示走"字典轨接口 + 封闭轨前端常量"（双轨 SR-7），不自行翻译。

---

## 3. 业务链承载矩阵

### 3.1 主生产追溯链（必须 PC 完整承载）

| 链环节 | PC 承载页面（模块） | 冻结实体 | 状态 | 缺口 |
|---|---|---|---|---|
| 项目 | 项目管理-列表/详情（T1） | `md.main_project` | 🟡 | 只读，创建 API 缺 |
| 子项目 | 项目管理-子项目详情（T2） | `md.subproject` | 🟡 | 同上 |
| 构件清单 | 构件管理-清单 | `prod.component_list_item` | 🟡 | 导入服务缺 |
| 实际构件 | 构件管理-台账/详情 | `prod.actual_component` | 🟡 | 检索 API 缺 |
| 工序 | 工艺/工序-路线/工序字典 | `ref.operation_type`+`route_template_step` | 🟡 | 查看为主 |
| 生产计划 | 生产计划-编制 | `prod.production_plan(+_line)` | 🟡 | API 缺、无数据 |
| 生产任务 | 生产任务-分配/列表 | `prod.production_task` | 🟢 | 已有 API（待分页/鉴权） |
| 生产登记 | 生产登记-报工/履历 | `prod.production_report` | 🟢/🟡 | 手机写、PC 读 |
| 质量 | 质量管理-检验/返工/放行 | `prod.quality_*`/`rework_order`/`final_qualification` | 🟡 | **写入口为零（#5）** |
| 装托 | 托盘/包装-装托作业 | `ship.pallet_load` | 🟡 | API 缺 |
| 集装箱 | 集装箱/发运-装柜 | `ship.container_load` | 🟡 | API 缺 |
| 装柜 | 同上（状态 sealed） | `shipping_container` | 🟡 | API 缺 |
| 封柜 | 集装箱-状态机 sealed | `shipping_container` | 🟡 | 需经 unload/reload 正式动作 |
| 发运 | 集装箱/发运-确认 | `ship.shipment`+`shipment_pallet` | 🔴/🟡 | **M-P4-2 未执行（#4）** |

**结论**：除"质量写入口"与"发运托盘级（M-P4-2）"两处受已知阻塞外，PC 页面可完整承载该链。

### 3.2 工艺→计价链（必须 PC 完整承载）

| 链环节 | PC 承载页面（模块） | 冻结实体 | 状态 |
|---|---|---|---|
| 构件类型 | 工艺/工序-标准模板（查） | `ref.component_type_dict` | 🟡 |
| 标准工序模板 | 工艺/工序-模板 | `eng.component_type_process_template`/`_step` | 🟡 |
| 项目采用工艺路线 | 工艺/工序-路线 | `eng.route_template`（standard_template_id 追溯） | 🟡 |
| 班组可执行工序 | 班组/人员（不展示，表未建） | `md.team_operation_capability` | 🟡（仅能力表达，非强制校验） |
| 生产任务 | 生产任务 | `prod.production_task.execute_team_id` | 🟢 |
| 劳务计价 | 劳务计价-试算 | `eng.labor_pricing_rule×_version` > `project_operation_price` | 🟡（只读试算） |

**结论**：链完整可达；`team_operation_capability` 仅作能力参考、不作派工强制校验（D-2 铁律）；`labor_pricing_condition` 未接入（不假设生效）。

---

## 4. 与现有 `pc_frontend_phase1_*.md` 的对应关系

| 现有 Phase 1 文档 | 在本功能地图中的对应 | 关系判定 |
|---|---|---|
| `pc_frontend_baseline.md` | 模块总表/页面清单/API 缺口/开发顺序 → 本图 §1/§2/§7 直接继承并扩到全 14 模块 | **主来源**，已整合 |
| `pc_frontend_phase1_kickoff_decision.md` | 阶段1 范围（曾排除驾驶舱/质量/仓储/装托/发运/设备/系统） | **被本图 supersede**（用户本轮要求纳入全模块） |
| `pc_frontend_phase1_uiux.md` / `_wireframe_api_contract.md` | 窄菜单（工作台/项目/生产/组织）+ 页面 P1~P9 | 子集；其页面映射进本图对应模块 |
| `pc_frontend_phase1_enum_mapping_draft.md` | 16 枚举中文映射 → 系统管理-字典/中文显示策略 | 对应 |
| `pc_frontend_phase1_final_adjudication.md` | Q-23(工序全集)/Q-26(team_type) RED 裁决 | 对应冲突 #2/#3 |
| `pc_frontend_phase1_business_confirm_and_blocklist.md` | 业务确认+BLK 阻断清单 | 对应冲突/待确认项 |
| `pc_frontend_phase1_model_impact_review.md` / `_minimal_structure_review.md` / `_decision_record_and_gate_evidence.md` / `_team_type_and_occupation_review.md` | team_type 存废、occupation M:N、team_operation 结构 | 对应模块 9 + 冲突 #3 |
| `pc_frontend_phase1_operation_statistics_and_settlement_*.md` | 劳务计价/统计口径、计量规则、六类口径 | 对应模块 10 + 冲突 #10 |
| `pc_frontend_phase1_fabrication_shipping_boundary_and_statistics_model_review.md` | 制作 vs 发运边界、托盘级发运 | 对应模块 11/12 + 冲突 #4 |
| `pc_frontend_phase1_final_business_recheck_and_pre_remediation_review.md` / `_remediation_execution_plan.md` | 整改前核查/执行方案（⏸ 已暂停） | 作为背景上下文，非当前事实 |

> **一句话**：本功能地图 = `pc_frontend_baseline.md`（全量模块骨架）之上，吸收其余 14 份文档的页面细节、冲突与待确认项，按用户本轮"全 14 模块"要求统一整合而成；窄范围文档的排除项已被用户本轮指令覆盖。

---

## 5. 冲突 / 缺口清单（仅记录，不修改 V1.2）

| # | 冲突/缺口 | 来源 | 对功能地图影响 | 处理原则 |
|---|---|---|---|---|
| 1 | **命名冲突**：用户链 `component_processes`/`process_register_logs` 在冻结模型不存在，实为 `production_task`/`production_report` | 冻结文档 grep 0 命中 | 功能地图已用冻结名，旧名作别名待确认 | 不改库；仅记录 |
| 2 | **工序全集口径**：DB seed 16 条 vs 业务 19 道 vs 旧系统 9 道 | final_adjudication Q-23 / business_confirm | 工序下拉/路线种子须以 DB 16 为准，待裁决 | 不改 operation_type；待业务拍板 |
| 3 | **team_type 值域**：DB 实测 4 值 vs R36 2 值；拟删除 | team_type_review / final_adjudication Q-26 | 班组页"类型"列待定 | 以 DB 为准；存废待裁决 |
| 4 | **发运托盘级阻塞**：`ship.shipment_pallet`（M-P4-2）未执行 | baseline §7.3 / fabrication_shipping | 模块 12 发运草稿/按托加入无法实现 | 排开发顺序末段，先执行 M-P4-2 |
| 5 | **质量零写入路径**：表/触发器齐全但无 API/录入逻辑 | business_decision_pending RED-C2/RED-B2 | 模块 8 页面可画，写入口待定 | 是否 Phase 1 实现待业务确认 |
| 6 | **缺料拦截分歧**：`system_config.material_shortage_intercept=true` 硬拦截 vs N-16 推荐"只预警" | baseline NEW-1 | 计划下达交互行为未定 | 默认值分歧，待确认 |
| 7 | **无考勤/无安全库存模型** | baseline NEW-5/6 | 人员出勤异常/库存预警无法实现 | 若要做属语义变更，须走架构变更流程 |
| 8 | **权限表未 seed + 无鉴权逻辑**；3 读接口无鉴权 | baseline NEW-3/4 | 角色菜单/按钮显隐只能占位 | 待 N-27 定稿+seed；阶段1 仅登录 |
| 9 | **labor_pricing_condition 未接入计价链** | R7 ORANGE-1 | 模块 10 UI 不得展示"已按条件计价" | 冻结事实，不假设生效 |
| 10 | **统计多口径冲突**：完成重量(实测vs图纸 RED-B3)、成品检双重身份、loading 工序越界、P4-3 受影响 | statistics_model_review / business_decision_pending | 模块 10/驾驶舱口径待统一 | 不改规则；待业务确认 |
| 11 | **production_completed 触发点分歧**：painting 触发 vs 车间主体完成 | fabrication_shipping E / business_decision_pending | 驾驶舱"完成量"口径 | G-2 冻结为 painting；待确认 |

---

## 6. 必须由工厂业务确认的事项（不代拍板）

| # | 待确认事项 | 影响模块 | 关联冲突 |
|---|---|---|---|
| B1 | `team_type` 值域/存废（4 值 vs 2 值 vs 删） | 9 | #3 |
| B2 | 阶段 1 工序全集（16/18/19？同义名是否合并） | 4/6/7 | #2 |
| B3 | `production_completed` 触发机制（painting vs 车间主体完成） | 1/7 | #11 |
| B4 | "最终合格日期"取哪一列（检验 pass / final_qualification） | 8 | #10 |
| B5 | 车间产量重量口径（图纸/清单重 vs 实测重优先） | 1/10 | #10 |
| B6 | "车间"如何落地（虚拟/新建实体/全班组汇总） | 1/10 | #10 |
| B7 | 返工五问（扣产/重结算/单价/指标/多次） | 8/10 | — |
| B8 | 价格是否含班组维度（同工序不同班组不同价） | 10 | #10 |
| B9 | 缺料拦截 vs 预警（system_config 默认 true） | 5 | #6 |
| B10 | 双完成率是否并列（生产完成 vs 质量合格） | 1/8 | #10 |
| B11 | 安全库存/考勤是否纳入 V1（当前模型无） | 9/11 | #7 |
| B12 | 成本/计件金额是否上驾驶舱（V1 不做财务核算） | 1/10 | §八口径 |
| B13 | 质量写入口是否纳入 Phase 1（当前零路径） | 8 | #5 |
| B14 | 发运是否随 M-P4-2 后做、封条是否建（Q6 不建） | 12 | #4 |

---

## 7. 推荐 Phase 1 开发顺序

> 原则：**先做"后端已具备/数据可驱动且不依赖未决规则"的页面；把依赖未执行迁移或未决规则的模块排后；治理类配置排最后。**

| 阶段 | 模块/页面 | 依赖 | 说明 |
|---|---|---|---|
| **阶段 0 前置**（不写 UI） | F6 前端工程归属（已授权建 Vue3）、技术栈骨架、API 清单授权 | — | 当前 BLOCKED→已授权，待建工程 |
| **阶段 1 最小骨架**（唯一完整后端闭环） | 登录+框架 → 班组列表(补分配阻塞点) → 任务分配 → 任务列表(补分页) → 生产履历 | 已有 tasks/history API（补鉴权/分页） | 分配→报工→履历，立即产生价值 |
| **阶段 2 项目+构件** | 项目列表/详情 → 子项目 → 构件清单/详情 → **清单导入**（最高频刚需，工作量最大） | 新增 projects/components/imports API | 打通"项目→清单→构件" |
| **阶段 3 驾驶舱 A 档** | 一屏数字(核心8~10项)+风险榜A档+下钻 | dashboard 聚合 API | 不含六指标/发运托盘进度/成本(待确认) |
| **阶段 4 工艺/工序 + 劳务计价查看** | 工序字典/路线查看、计价规则查看、计价试算只读 | 新增工艺/计价查询 API（视图已就绪） | 配置与试算，不开放自定义工序/改价 |
| **阶段 5 生产计划** | 计划编制+版本+六指标(P-14) | plans API + 计划数据 | 驾驶舱升级含健康度 |
| **阶段 6 质量 + 仓储 + 装托** | 质量(检验/缺陷/返工/放行，若 B13 确认) → 仓储 → 装托 | 质量/仓储/装托 API | 质量写入口待 B13 |
| **阶段 7 集装箱/发运** | 装柜/发运确认/混装/签收 | **先执行 M-P4-2（shipment_pallet）** + 发运 API | 受 #4 阻塞，排末段 |
| **阶段 8 设备 + 人员组织 + 系统管理 + 治理** | 设备台账/影响链 → 人员/班组/账号 → 字典/审计/异常/更正/权限占位 | 各域 API；权限待 N-27 | "按角色显隐"先占位 |

**一句话总结**：先"能干活"（分配→履历），再"能看"（项目→构件），再"能管"（驾驶舱 A 档），然后"能算"（计划六指标/计价试算），再"能控"（质量/仓储/装托），最后"能发运"（需 M-P4-2）与"能配"（治理）。

---

## 8. 附录

### 8.1 V1.2 核心实体速查（PC 功能地图引用）

- **项目域**：`md.main_project`、`md.subproject`、`aud.project_status_history`
- **构件域**：`prod.component_list_item`、`prod.actual_component`、`prod.qr_code_registry`、`imp.*`（导入）
- **工艺/工序域**：`ref.operation_type`、`eng.route_template`、`eng.route_template_step`、`eng.component_type_process_template/_step`、`eng.project_operation/_price`
- **计划/任务/登记域**：`prod.production_plan(+_version/_line)`、`prod.production_task`、`prod.production_report(+_worker/_measure)`、`prod.task_participant`、`prod.primary_team_assignment`
- **质量/返工域**：`prod.quality_inspection`、`prod.quality_defect`、`prod.ncr`、`prod.rework_order`、`prod.final_qualification`、`ref.inspection_type`
- **装托/发运域(`ship`)**：`pallet`/`pallet_load`/`pallet_load_history`/`pallet_weight_record`、`shipping_container`/`container_load`、`shipment`/`shipment_snapshot`/`shipment_pallet`(🔴M-P4-2未执行)/`mixed_load_authorization`/`shipment_event`/`site_delivery_record`
- **班组/人员域**：`md.team`、`md.team_membership`、`md.employee`、`md.team_operation_capability`、`md.employee_occupation`、`ref.employee_occupation_dict`、`user_account`、`role`
- **劳务计价域**：`eng.labor_pricing_rule`/`_version`/`_condition`、`eng.project_operation_price`、视图 `eng.v_operation_cost_trial`/`v_project_production_cost`
- **设备域**：`prod.equipment`/`equipment_event`/`equipment_impact`
- **系统/治理域**：`ref.*`(13字典)、`aud.operation_log`/`exception_*`/`correction_*`/`approval_record`、`md.permission`/`role_permission`/`data_scope_policy`/`segregation_rule`

### 8.2 冻结规则红线（PC 功能地图不得违反）

- `responsibility_kind` 四态（NULL/TEAM/NON_TEAM/PENDING）+ `chargeability` 三值；NULL+chargeable 与 PENDING+chargeable DB 层拒；TEAM⇒responsible_team_id 必存在；NON_TEAM⇒必空；PENDING/NULL 不产生正式计价。
- 劳务计价 M7：项目价 > 基础价 > MISSING_PRICE（不 0 兜底）；`labor_pricing_condition` 未接入。
- `actual_component` 隐含数量 1、无 quantity 列；多件由清单 quantity 展开。
- `production_task` 单一 `execute_team_id`；横向承包；主责≠执行。
- 阶段 1 仅"登录+get_current_user"，不做菜单隐藏；登录≠有权限。
- 发运前置仅 `final_qualification` 有效事实；托盘=发运操作单位；封条不建。
- V1.2 仅提供计件劳务计价与成本试算，**不建设财务总账/应付/正式财务成本核算，不替代 ERP**。

---

**文档状态**：功能地图完成，等待人工确认；未进入编码、未改 V1.2 冻结规则。
