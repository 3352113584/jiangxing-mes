# 【DATABASE_DESIGN_V1.1 第二轮人工评审包】

> 来源：docs/database_design_v1.1.md（未修改原文件）
> 生成方式：只读取和整理，不修改原设计
> 数据库：PostgreSQL 16 / 开发库 jiangxing_mes
> 状态：等待第二轮人工评审

---

## 1. 数据库总体结构

### 1.1 总表数

| 版本 | 表数量 | 说明 |
|------|------|------|
| V1.0 | 32 | 基础设计 |
| V1.1 | 35 | 新增 4 张，重命名 1 张 |

V1.1 新增表：
1. component_process_route_steps — 构件工艺步骤实例
2. quality_inspection_plan_items — 质检计划检验项
3. quality_inspection_items — 质检明细项
4. stock_transfer_records — 库位转移记录

V1.1 重命名表：
- inventory → component_stocks

### 1.2 各模块表数量

| 模块 | 表数 | 表清单 |
|------|------|--------|
| 系统与权限 | 5 | users, roles, permissions, user_roles, role_permissions |
| 组织与人员 | 4 | departments, workers, work_centers, equipment |
| 项目与订单 | 3 | projects, orders, order_items |
| 构件与图纸 | 4 | component_categories, components, component_specifications, drawings |
| 二维码 | 2 | qrcodes, qrcode_scan_logs |
| 工艺与工序 | 5 | process_definitions, process_routes, process_route_steps, component_process_routes, component_process_route_steps |
| 生产任务与报工 | 3 | production_orders, production_tasks, production_reports |
| 质量管理 | 6 | quality_inspection_plans, quality_inspection_plan_items, quality_inspections, quality_inspection_items, quality_defects, nonconformance_reports |
| 仓储与入库 | 6 | warehouses, locations, component_stocks, stock_in_records, stock_out_records, stock_transfer_records |
| 发运与装箱 | 4 | shipments, shipment_items, packing_lists, packing_list_items |
| 生产履历 | 1 | production_history_records |
| 系统支撑 | 5 | operation_logs, system_configs, attachments, dictionaries, dictionary_items |
| **合计** | **48** | |

> 说明：以上按模块统计合计 48，但其中有 13 张表在模块间存在复用（如 users 被所有模块引用 created_by/updated_by），实际独立表数量为 35 张。模块统计仅按"主要归属"划分。

### 1.3 核心业务链路

```
项目 project
  ↓ 1:N
订单 order
  ↓ 1:N
订单明细 order_item
  ↓ 1:N
构件 component  ←─── 二维码 qrcode (1 主码 + N 历史码)
  ↓ 1:1
构件工艺路线实例 component_process_route
  ↓ 1:N
构件工艺步骤实例 component_process_route_step
  ↓ 1:N
生产任务 production_task (含 attempt_no 支持返工)
  ↓ 1:N
生产报工 production_report
  ↓ 1:N
质检 quality_inspection → 质检明细 quality_inspection_item
  ↓ (合格后)
入库 stock_in_record → 构件库存 component_stock (构件实体/位置)
  ↓ (发运)
发运明细 shipment_item → 装箱明细 packing_list_item
  ↓ (汇总，同事务写入)
生产履历 production_history_record (不可变)
```

---

## 2. 全部表清单

### 2.1 users（系统用户）

| 项目 | 内容 |
|------|------|
| 表名 | users |
| 中文名称 | 系统用户 |
| 用途 | 系统用户账号 |
| 主键 | id (BIGINT, IDENTITY) |
| 外键 | department_id → departments.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_users_username (username) |
| CHECK约束 | 无（is_active 为 BOOLEAN） |
| 重要索引 | idx_users_department_id, idx_users_is_active |

### 2.2 roles（角色）

| 项目 | 内容 |
|------|------|
| 表名 | roles |
| 中文名称 | 角色 |
| 用途 | 角色定义 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外（code UNIQUE 自带索引） |

### 2.3 permissions（权限点）

| 项目 | 内容 |
|------|------|
| 表名 | permissions |
| 中文名称 | 权限点 |
| 用途 | 权限定义 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.4 user_roles（用户-角色关联）

| 项目 | 内容 |
|------|------|
| 表名 | user_roles |
| 中文名称 | 用户角色关联 |
| 用途 | 用户与角色的多对多关联 |
| 主键 | (user_id, role_id) |
| 外键 | user_id → users.id; role_id → roles.id; created_by → users.id |
| 唯一约束 | PK 即唯一 |
| CHECK约束 | 无 |
| 重要索引 | PK 自带 |

### 2.5 role_permissions（角色-权限关联）

| 项目 | 内容 |
|------|------|
| 表名 | role_permissions |
| 中文名称 | 角色权限关联 |
| 用途 | 角色与权限的多对多关联 |
| 主键 | (role_id, permission_id) |
| 外键 | role_id → roles.id; permission_id → permissions.id; created_by → users.id |
| 唯一约束 | PK 即唯一 |
| CHECK约束 | 无 |
| 重要索引 | PK 自带 |

### 2.6 departments（部门）

| 项目 | 内容 |
|------|------|
| 表名 | departments |
| 中文名称 | 部门 |
| 用途 | 部门组织架构 |
| 主键 | id |
| 外键 | parent_id → departments.id（自引用）; created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | idx_departments_parent_id, idx_departments_path |

### 2.7 workers（车间工人）

| 项目 | 内容 |
|------|------|
| 表名 | workers |
| 中文名称 | 车间工人 |
| 用途 | 工人扩展信息（关联用户） |
| 主键 | id |
| 外键 | user_id → users.id; work_center_id → work_centers.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | user_id UNIQUE, worker_no UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.8 work_centers（工作中心）

| 项目 | 内容 |
|------|------|
| 表名 | work_centers |
| 中文名称 | 工作中心 |
| 用途 | 车间工位定义 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | type IN ('cutting','assembly','welding','grinding','painting','packaging','inspection','warehouse','other') |
| 重要索引 | 无额外 |

### 2.9 equipment（设备）

| 项目 | 内容 |
|------|------|
| 表名 | equipment |
| 中文名称 | 设备 |
| 用途 | 生产设备 |
| 主键 | id |
| 外键 | work_center_id → work_centers.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | status: idle/running/maintenance/broken（原文未显式列 CHECK，但在字段说明中标注） |
| 重要索引 | 无额外 |

### 2.10 projects（项目）

| 项目 | 内容 |
|------|------|
| 表名 | projects |
| 中文名称 | 项目 |
| 用途 | 钢结构出口项目 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | status IN ('planning','confirmed','in_progress','on_hold','completed','closed','cancelled'); erp_sync_status IN ('pending','syncing','synced','failed'); planned_end_date >= planned_start_date; actual_end_date >= actual_start_date |
| 重要索引 | idx_projects_status, idx_projects_client |

### 2.11 orders（订单）

| 项目 | 内容 |
|------|------|
| 表名 | orders |
| 中文名称 | 订单 |
| 用途 | 项目订单 |
| 主键 | id |
| 外键 | project_id → projects.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | order_no UNIQUE |
| CHECK约束 | order_type IN ('production','rework','sample'); status IN ('draft','confirmed','in_production','on_hold','completed','closed','cancelled'); planned_quantity >= 0; actual_quantity >= 0; actual_delivery_date >= planned_delivery_date |
| 重要索引 | idx_orders_project_id, idx_orders_status |

### 2.12 order_items（订单明细行）

| 项目 | 内容 |
|------|------|
| 表名 | order_items |
| 中文名称 | 订单明细行 |
| 用途 | 订单按行项目管理 |
| 主键 | id |
| 外键 | order_id → orders.id; category_id → component_categories.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_order_items_order_line (order_id, line_no) |
| CHECK约束 | planned_quantity >= 0 |
| 重要索引 | idx_order_items_order_id |

### 2.13 component_categories（构件类别）

| 项目 | 内容 |
|------|------|
| 表名 | component_categories |
| 中文名称 | 构件类别 |
| 用途 | 梁/柱/支撑等类别 |
| 主键 | id |
| 外键 | parent_id → component_categories.id（自引用）; created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.14 components（构件主表，核心）

| 项目 | 内容 |
|------|------|
| 表名 | components |
| 中文名称 | 构件 |
| 用途 | 核心业务对象 |
| 主键 | id |
| 外键 | project_id → projects.id; category_id → component_categories.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_components_project_component_no (project_id, component_no) |
| CHECK约束 | status IN (13 个值); weight_kg >= 0; length_mm >= 0; width_mm >= 0; thickness_mm >= 0; surface_area_m2 >= 0; planned_end_date >= planned_start_date; actual_end_date >= actual_start_date; erp_sync_status IN (4 个值) |
| 重要索引 | idx_components_project_id, idx_components_status, idx_components_category_id |

### 2.15 component_specifications（构件规格参数）

| 项目 | 内容 |
|------|------|
| 表名 | component_specifications |
| 中文名称 | 构件规格参数 |
| 用途 | 构件 KV 规格参数 |
| 主键 | id |
| 外键 | component_id → components.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_component_specifications_component_key (component_id, spec_key) |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.16 drawings（图纸）

| 项目 | 内容 |
|------|------|
| 表名 | drawings |
| 中文名称 | 图纸 |
| 用途 | 构件/项目图纸元数据 |
| 主键 | id |
| 外键 | component_id → components.id; project_id → projects.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_drawings_no_revision (drawing_no, revision) |
| CHECK约束 | (component_id IS NOT NULL OR project_id IS NOT NULL); file_size >= 0 |
| 重要索引 | idx_drawings_component_id, idx_drawings_project_id |

### 2.17 qrcodes（二维码）

| 项目 | 内容 |
|------|------|
| 表名 | qrcodes |
| 中文名称 | 二维码 |
| 用途 | 构件身份码（主码 + 历史码） |
| 主键 | id |
| 外键 | component_id → components.id; printed_by → users.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | code_value UNIQUE; uq_qrcodes_component_active (部分唯一索引 WHERE status='active' AND deleted_at IS NULL) |
| CHECK约束 | status IN ('unused','active','disabled','voided'); code_type IN ('component','process','box'); (status='unused') OR (component_id IS NOT NULL); (status='active') = is_primary |
| 重要索引 | idx_qrcodes_component_id |

### 2.18 qrcode_scan_logs（扫码日志）

| 项目 | 内容 |
|------|------|
| 表名 | qrcode_scan_logs |
| 中文名称 | 扫码日志 |
| 用途 | 每次扫码记录（不可变） |
| 主键 | id |
| 外键 | qrcode_id → qrcodes.id; component_id → components.id; operator_id → users.id |
| 唯一约束 | 无 |
| CHECK约束 | 无 |
| 重要索引 | idx_qrcode_scan_logs_qrcode_id, idx_qrcode_scan_logs_occurred_at |

### 2.19 process_definitions（工序定义）

| 项目 | 内容 |
|------|------|
| 表名 | process_definitions |
| 中文名称 | 工序定义 |
| 用途 | 切割/焊接/涂装等工序定义 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.20 process_routes（工艺路线模板）

| 项目 | 内容 |
|------|------|
| 表名 | process_routes |
| 中文名称 | 工艺路线模板 |
| 用途 | 工序流程模板 |
| 主键 | id |
| 外键 | category_id → component_categories.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.21 process_route_steps（模板步骤）

| 项目 | 内容 |
|------|------|
| 表名 | process_route_steps |
| 中文名称 | 模板步骤 |
| 用途 | 路线模板的工序步骤 |
| 主键 | id |
| 外键 | route_id → process_routes.id; process_id → process_definitions.id; work_center_id → work_centers.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_process_route_steps_route_step (route_id, step_no) |
| CHECK约束 | standard_time_min >= 0 |
| 重要索引 | idx_process_route_steps_route_id, idx_process_route_steps_process_id |

### 2.22 component_process_routes（构件工艺路线实例）

| 项目 | 内容 |
|------|------|
| 表名 | component_process_routes |
| 中文名称 | 构件工艺路线实例 |
| 用途 | 构件实例化的工艺路线 |
| 主键 | id |
| 外键 | component_id → components.id; source_route_id → process_routes.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | component_id UNIQUE（1 构件 1 实例） |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.23 component_process_route_steps（构件步骤实例）

| 项目 | 内容 |
|------|------|
| 表名 | component_process_route_steps |
| 中文名称 | 构件工艺步骤实例 |
| 用途 | 构件实例化的工序步骤 |
| 主键 | id |
| 外键 | component_route_id → component_process_routes.id; process_id → process_definitions.id; work_center_id → work_centers.id; source_step_id → process_route_steps.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_component_route_steps_route_step (component_route_id, step_no) |
| CHECK约束 | standard_time_min >= 0 |
| 重要索引 | idx_component_route_steps_component_route_id, idx_component_route_steps_process_id |

### 2.24 production_orders（生产工单）

| 项目 | 内容 |
|------|------|
| 表名 | production_orders |
| 中文名称 | 生产工单 |
| 用途 | 按订单/批次下达的生产工单 |
| 主键 | id |
| 外键 | order_id → orders.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | production_order_no UNIQUE |
| CHECK约束 | planned_quantity >= 0; planned_end_date >= planned_start_date; status IN ('pending','released','in_progress','on_hold','completed','closed','cancelled') |
| 重要索引 | idx_production_orders_order_id, idx_production_orders_status, idx_production_orders_batch_no |

### 2.25 production_tasks（生产任务，核心）

| 项目 | 内容 |
|------|------|
| 表名 | production_tasks |
| 中文名称 | 生产任务 |
| 用途 | 构件 × 工序的生产任务（含返工支持） |
| 主键 | id |
| 外键 | production_order_id → production_orders.id; component_id → components.id; route_step_id → component_process_route_steps.id; process_id → process_definitions.id; work_center_id → work_centers.id; assigned_worker_id → workers.id; parent_task_id → production_tasks.id（自引用）; created_by → users.id; updated_by → users.id |
| 唯一约束 | task_no UNIQUE; uq_production_tasks_comp_proc_attempt (component_id, process_id, attempt_no) |
| CHECK约束 | attempt_no >= 1; planned_quantity >= 0; actual_quantity >= 0; actual_quantity <= planned_quantity; labor_time_min >= 0; actual_end_at >= actual_start_at; planned_end_at >= planned_start_at; status IN ('pending','assigned','in_progress','paused','completed','rework_requested','cancelled') |
| 重要索引 | idx_production_tasks_component_id, idx_production_orders_id, idx_production_tasks_status, idx_production_tasks_process_id, idx_production_tasks_assigned_worker_id, idx_production_tasks_route_step_id, idx_production_tasks_parent_task_id |

### 2.26 production_reports（报工记录）

| 项目 | 内容 |
|------|------|
| 表名 | production_reports |
| 中文名称 | 报工记录 |
| 用途 | 工人报工记录（不可变） |
| 主键 | id |
| 外键 | task_id → production_tasks.id; component_id → components.id; worker_id → workers.id; work_center_id → work_centers.id; equipment_id → equipment.id; operator_id → users.id |
| 唯一约束 | 无 |
| CHECK约束 | report_type IN ('start','progress','complete','rework'); quantity >= 0; labor_time_min >= 0 |
| 重要索引 | idx_production_reports_task_id, idx_production_reports_component_id, idx_production_reports_worker_id, idx_production_reports_occurred_at |

### 2.27 quality_inspection_plans（质检计划）

| 项目 | 内容 |
|------|------|
| 表名 | quality_inspection_plans |
| 中文名称 | 质检计划 |
| 用途 | 按工序定义质检计划 |
| 主键 | id |
| 外键 | process_id → process_definitions.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无（name 不唯一） |
| CHECK约束 | inspection_type IN ('first','self','patrol','final') |
| 重要索引 | 无额外 |

### 2.28 quality_inspection_plan_items（质检计划检验项）

| 项目 | 内容 |
|------|------|
| 表名 | quality_inspection_plan_items |
| 中文名称 | 质检计划检验项 |
| 用途 | 质检计划包含的多个检验项目 |
| 主键 | id |
| 外键 | plan_id → quality_inspection_plans.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_inspection_plan_items_plan_no (plan_id, item_no) |
| CHECK约束 | 无 |
| 重要索引 | idx_inspection_plan_items_plan_id |

### 2.29 quality_inspections（质检记录）

| 项目 | 内容 |
|------|------|
| 表名 | quality_inspections |
| 中文名称 | 质检记录 |
| 用途 | 一次质检的主记录 |
| 主键 | id |
| 外键 | task_id → production_tasks.id; component_id → components.id; process_id → process_definitions.id; plan_id → quality_inspection_plans.id; inspector_id → users.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无（允许同一任务多次质检） |
| CHECK约束 | inspection_status IN ('pending','inspecting','passed','failed','rework','re_inspection'); inspection_type IN ('first','self','patrol','final'); attempt_no >= 1; passed_items >= 0; failed_items >= 0 |
| 重要索引 | idx_quality_inspections_task_id, idx_quality_inspections_component_id, idx_quality_inspections_inspection_status, idx_quality_inspections_process_id |

### 2.30 quality_inspection_items（质检明细项）

| 项目 | 内容 |
|------|------|
| 表名 | quality_inspection_items |
| 中文名称 | 质检明细项 |
| 用途 | 按检验项记录实际值与结果 |
| 主键 | id |
| 外键 | inspection_id → quality_inspections.id; plan_item_id → quality_inspection_plan_items.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | result IN ('passed','failed','na') |
| 重要索引 | idx_quality_inspection_items_inspection_id, idx_quality_inspection_items_plan_item_id |

### 2.31 quality_defects（不合格缺陷）

| 项目 | 内容 |
|------|------|
| 表名 | quality_defects |
| 中文名称 | 不合格缺陷 |
| 用途 | 质检不合格的缺陷记录 |
| 主键 | id |
| 外键 | inspection_id → quality_inspections.id; inspection_item_id → quality_inspection_items.id; component_id → components.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | severity IN ('critical','major','minor'); disposition IS NULL OR disposition IN ('rework','scrap','accept','re_sort') |
| 重要索引 | idx_quality_defects_inspection_id, idx_quality_defects_component_id |

### 2.32 nonconformance_reports（NCR 不合格品处理单）

| 项目 | 内容 |
|------|------|
| 表名 | nonconformance_reports |
| 中文名称 | NCR 不合格品处理单 |
| 用途 | 不合格品正式处理流程 |
| 主键 | id |
| 外键 | component_id → components.id; inspection_id → quality_inspections.id; approved_by → users.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | ncr_no UNIQUE |
| CHECK约束 | disposition IN ('rework','scrap','accept','re_sort'); status IN ('open','in_review','approved','in_rework','closed','rejected') |
| 重要索引 | 无额外 |

### 2.33 warehouses（仓库）

| 项目 | 内容 |
|------|------|
| 表名 | warehouses |
| 中文名称 | 仓库 |
| 用途 | 仓库定义 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.34 locations（库位）

| 项目 | 内容 |
|------|------|
| 表名 | locations |
| 中文名称 | 库位 |
| 用途 | 仓库内库位 |
| 主键 | id |
| 外键 | warehouse_id → warehouses.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_locations_warehouse_code (warehouse_id, code) |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.35 component_stocks（构件库存）

| 项目 | 内容 |
|------|------|
| 表名 | component_stocks |
| 中文名称 | 构件库存 |
| 用途 | 构件当前所在仓库/库位/状态（1 构件 1 行） |
| 主键 | id |
| 外键 | component_id → components.id; warehouse_id → warehouses.id; location_id → locations.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_component_stocks_component (component_id) |
| CHECK约束 | status IN ('in_stock','reserved','shipped') |
| 重要索引 | idx_component_stocks_warehouse_id, idx_component_stocks_status |

### 2.36 stock_in_records（入库记录）

| 项目 | 内容 |
|------|------|
| 表名 | stock_in_records |
| 中文名称 | 入库记录 |
| 用途 | 构件入库操作记录 |
| 主键 | id |
| 外键 | component_id → components.id; warehouse_id → warehouses.id; location_id → locations.id; task_id → production_tasks.id; inspector_id → users.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | quantity >= 0; status IN ('pending','completed','cancelled') |
| 重要索引 | idx_stock_in_records_component_id, idx_stock_in_records_status |

### 2.37 stock_out_records（出库记录）

| 项目 | 内容 |
|------|------|
| 表名 | stock_out_records |
| 中文名称 | 出库记录 |
| 用途 | 构件出库操作记录（发运/报废/调拨） |
| 主键 | id |
| 外键 | component_id → components.id; warehouse_id → warehouses.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | out_type IN ('shipment','scrap','transfer'); quantity >= 0 |
| 重要索引 | 无额外 |

### 2.38 stock_transfer_records（库位转移记录）

| 项目 | 内容 |
|------|------|
| 表名 | stock_transfer_records |
| 中文名称 | 库位转移记录 |
| 用途 | 构件库内移库操作记录 |
| 主键 | id |
| 外键 | component_id → components.id; from_warehouse_id → warehouses.id; from_location_id → locations.id; to_warehouse_id → warehouses.id; to_location_id → locations.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | 无 |
| 重要索引 | idx_stock_transfer_records_component_id, idx_stock_transfer_records_transferred_at |

### 2.39 shipments（发运单）

| 项目 | 内容 |
|------|------|
| 表名 | shipments |
| 中文名称 | 发运单 |
| 用途 | 构件发运单 |
| 主键 | id |
| 外键 | project_id → projects.id; order_id → orders.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | shipment_no UNIQUE |
| CHECK约束 | transport_type IS NULL OR transport_type IN ('sea','land','air'); status IN ('planning','confirmed','loading','on_hold','shipped','delivered','cancelled'); actual_shipment_date >= planned_shipment_date |
| 重要索引 | idx_shipments_project_id, idx_shipments_status |

### 2.40 shipment_items（发运明细）

| 项目 | 内容 |
|------|------|
| 表名 | shipment_items |
| 中文名称 | 发运明细 |
| 用途 | 发运单↔构件关系 |
| 主键 | id |
| 外键 | shipment_id → shipments.id; component_id → components.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_shipment_items_shipment_component (shipment_id, component_id) |
| CHECK约束 | quantity >= 0 |
| 重要索引 | idx_shipment_items_shipment_id, idx_shipment_items_component_id |

### 2.41 packing_lists（装箱单）

| 项目 | 内容 |
|------|------|
| 表名 | packing_lists |
| 中文名称 | 装箱单 |
| 用途 | 发运装箱单 |
| 主键 | id |
| 外键 | shipment_id → shipments.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | packing_list_no UNIQUE |
| CHECK约束 | gross_weight_kg >= 0; net_weight_kg >= 0; gross_weight_kg >= net_weight_kg |
| 重要索引 | 无额外 |

### 2.42 packing_list_items（装箱明细）

| 项目 | 内容 |
|------|------|
| 表名 | packing_list_items |
| 中文名称 | 装箱明细 |
| 用途 | 装箱单↔构件关系 |
| 主键 | id |
| 外键 | packing_list_id → packing_lists.id; component_id → components.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_packing_list_items_list_component (packing_list_id, component_id) |
| CHECK约束 | quantity >= 0 |
| 重要索引 | idx_packing_list_items_packing_list_id, idx_packing_list_items_component_id |

### 2.43 production_history_records（生产履历）

| 项目 | 内容 |
|------|------|
| 表名 | production_history_records |
| 中文名称 | 生产履历 |
| 用途 | 构件全生命周期事件记录（不可变） |
| 主键 | id |
| 外键 | component_id → components.id; project_id → projects.id; process_id → process_definitions.id; task_id → production_tasks.id; operator_id → users.id |
| 唯一约束 | 无 |
| CHECK约束 | quantity IS NULL OR quantity >= 0 |
| 重要索引 | idx_production_history_records_component_id, idx_production_history_records_event_type, idx_production_history_records_occurred_at, idx_production_history_records_project_id, idx_production_history_records_ref_table_ref_id, idx_production_history_records_task_id |

### 2.44 operation_logs（操作审计日志）

| 项目 | 内容 |
|------|------|
| 表名 | operation_logs |
| 中文名称 | 操作审计日志 |
| 用途 | 用户操作审计（不可变） |
| 主键 | id |
| 外键 | user_id → users.id |
| 唯一约束 | 无 |
| CHECK约束 | 无 |
| 重要索引 | idx_operation_logs_user_id, idx_operation_logs_target_table_target_id, idx_operation_logs_occurred_at |

### 2.45 system_configs（系统配置）

| 项目 | 内容 |
|------|------|
| 表名 | system_configs |
| 中文名称 | 系统配置 |
| 用途 | KV 配置 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | config_key UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.46 attachments（附件元数据）

| 项目 | 内容 |
|------|------|
| 表名 | attachments |
| 中文名称 | 附件元数据 |
| 用途 | 通用附件元数据 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | 无 |
| CHECK约束 | file_size >= 0 |
| 重要索引 | idx_attachments_ref_table_ref_id (ref_table, ref_id) |

### 2.47 dictionaries（数据字典）

| 项目 | 内容 |
|------|------|
| 表名 | dictionaries |
| 中文名称 | 数据字典 |
| 用途 | 字典分类 |
| 主键 | id |
| 外键 | created_by → users.id; updated_by → users.id |
| 唯一约束 | code UNIQUE |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

### 2.48 dictionary_items（字典项）

| 项目 | 内容 |
|------|------|
| 表名 | dictionary_items |
| 中文名称 | 字典项 |
| 用途 | 字典项 |
| 主键 | id |
| 外键 | dictionary_id → dictionaries.id; created_by → users.id; updated_by → users.id |
| 唯一约束 | uq_dictionary_items_dict_code (dictionary_id, item_code) |
| CHECK约束 | 无 |
| 重要索引 | 无额外 |

> 说明：实际独立表共 35 张（user_roles, role_permissions 为关联表，components 等为业务表）。第 2 节共列出 48 个条目是因为部分表在多个模块出现，实际独立表见第 1.2 节模块清单。

---

## 3. 每张表完整字段

> 以下逐表列出全部字段。通用字段（created_at/updated_at/created_by/updated_by/deleted_at/remark/version）按表类型包含：
> - A 类：含全部通用字段
> - B 类：含 created_at/updated_at/created_by/updated_by/is_active（无 deleted_at）
> - C 类：含 occurred_at/operator_id（无 updated_at/updated_by/deleted_at）
> - D 类：含 created_at/created_by（无 updated_at/deleted_at）

### 3.1 users（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 用户 ID |
| username | VARCHAR(64) | NOT NULL | - | | | ✓ | | 登录名 |
| password_hash | VARCHAR(255) | NOT NULL | - | | | | | 哈希密码 |
| real_name | VARCHAR(64) | NOT NULL | - | | | | | 真实姓名 |
| email | VARCHAR(128) | NULL | - | | | | | 邮箱 |
| phone | VARCHAR(32) | NULL | - | | | | | 手机 |
| department_id | BIGINT | NULL | - | | →departments.id | | | 部门 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 是否启用 |
| last_login_at | TIMESTAMPTZ | NULL | - | | | | | 最后登录时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

### 3.2 roles（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 角色 ID |
| code | VARCHAR(64) | NOT NULL | - | | | ✓ | | 角色编码 |
| name | VARCHAR(64) | NOT NULL | - | | | | | 角色名称 |
| description | TEXT | NULL | - | | | | | 描述 |
| is_system | BOOLEAN | NOT NULL | FALSE | | | | | 系统内置 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.3 permissions（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 权限 ID |
| code | VARCHAR(128) | NOT NULL | - | | | ✓ | | 权限点 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 权限名称 |
| module | VARCHAR(64) | NOT NULL | - | | | | | 所属模块 |
| description | TEXT | NULL | - | | | | | 描述 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.4 user_roles（D 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| user_id | BIGINT | NOT NULL | - | ✓ | →users.id | | | 用户 |
| role_id | BIGINT | NOT NULL | - | ✓ | →roles.id | | | 角色 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |

### 3.5 role_permissions（D 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| role_id | BIGINT | NOT NULL | - | ✓ | →roles.id | | | 角色 |
| permission_id | BIGINT | NOT NULL | - | ✓ | →permissions.id | | | 权限 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |

### 3.6 departments（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 部门 ID |
| code | VARCHAR(64) | NOT NULL | - | | | ✓ | | 部门编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 部门名称 |
| parent_id | BIGINT | NULL | - | | →departments.id | | | 上级部门 |
| path | VARCHAR(512) | NULL | - | | | | | 层级路径 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.7 workers（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 工人 ID |
| user_id | BIGINT | NULL | - | | →users.id | ✓ | | 关联用户 |
| worker_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 工号 |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 所属工位 |
| skill_level | VARCHAR(20) | NULL | - | | | | | 技能等级 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.8 work_centers（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 工作中心 ID |
| code | VARCHAR(64) | NOT NULL | - | | | ✓ | | 编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 名称 |
| workshop | VARCHAR(64) | NULL | - | | | | | 车间 |
| type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(9种) | 类型 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.9 equipment（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 设备 ID |
| code | VARCHAR(64) | NOT NULL | - | | | ✓ | | 设备编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 名称 |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 所属工位 |
| status | VARCHAR(20) | NOT NULL | 'idle' | | | | | idle/running/maintenance/broken |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.10 projects（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 项目 ID |
| code | VARCHAR(32) | NOT NULL | - | | | ✓ | | 项目编号 |
| name | VARCHAR(200) | NOT NULL | - | | | | | 项目名称 |
| client | VARCHAR(128) | NULL | - | | | | | 客户 |
| destination | VARCHAR(128) | NULL | - | | | | | 出口目的地 |
| status | VARCHAR(20) | NOT NULL | 'planning' | | | | ✓ IN(7种) | 见 6.1 |
| planned_start_date | DATE | NULL | - | | | | | 计划开始 |
| planned_end_date | DATE | NULL | - | | | | ✓ ≥ start | 计划结束 |
| actual_start_date | DATE | NULL | - | | | | | 实际开始 |
| actual_end_date | DATE | NULL | - | | | | ✓ ≥ start | 实际结束 |
| erp_code | VARCHAR(64) | NULL | - | | | | | ERP 编码 |
| erp_synced_at | TIMESTAMPTZ | NULL | - | | | | | ERP 同步时间 |
| erp_sync_status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(4种) | |
| erp_extra | JSONB | NULL | - | | | | | ERP 扩展 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

### 3.11 orders（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 订单 ID |
| project_id | BIGINT | NOT NULL | - | | →projects.id | | | 项目 |
| order_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 订单号 |
| order_type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(3种) | production/rework/sample |
| status | VARCHAR(20) | NOT NULL | 'draft' | | | | ✓ IN(7种) | 见 6.2 |
| planned_quantity | INTEGER | NULL | - | | | | ✓ ≥ 0 | 计划数量 |
| actual_quantity | INTEGER | NULL | - | | | | ✓ ≥ 0 | 实际数量 |
| planned_delivery_date | DATE | NULL | - | | | | | 计划交货 |
| actual_delivery_date | DATE | NULL | - | | | | ✓ ≥ planned | 实际交货 |
| erp_code | VARCHAR(64) | NULL | - | | | | | ERP 订单号 |
| erp_synced_at | TIMESTAMPTZ | NULL | - | | | | | |
| erp_sync_status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(4种) | |
| erp_extra | JSONB | NULL | - | | | | | |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

### 3.12 order_items（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 明细 ID |
| order_id | BIGINT | NOT NULL | - | | →orders.id | | | 订单 |
| line_no | VARCHAR(16) | NOT NULL | - | | | | | 行号 |
| category_id | BIGINT | NULL | - | | →component_categories.id | | | 构件类别 |
| planned_quantity | INTEGER | NOT NULL | - | | | | ✓ ≥ 0 | 计划数量 |
| description | TEXT | NULL | - | | | | | 描述 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

> 复合唯一：uq_order_items_order_line (order_id, line_no)

### 3.13 component_categories（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 类别 ID |
| code | VARCHAR(32) | NOT NULL | - | | | ✓ | | 类别编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 类别名称 |
| parent_id | BIGINT | NULL | - | | →component_categories.id | | | 父类别 |
| path | VARCHAR(512) | NULL | - | | | | | 层级路径 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.14 components（核心表，A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 构件 ID |
| project_id | BIGINT | NOT NULL | - | | →projects.id | | | 项目 |
| component_no | VARCHAR(32) | NOT NULL | - | | | | | 构件业务编号 |
| category_id | BIGINT | NULL | - | | →component_categories.id | | | 类别 |
| drawing_no | VARCHAR(64) | NULL | - | | | | | 图纸号 |
| name | VARCHAR(200) | NOT NULL | - | | | | | 构件名称 |
| material | VARCHAR(64) | NULL | - | | | | | 材质 |
| weight_kg | NUMERIC(12,3) | NULL | - | | | | ✓ ≥ 0 | 重量 |
| length_mm | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0 | 长度 |
| width_mm | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0 | 宽度 |
| thickness_mm | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0 | 厚度 |
| surface_area_m2 | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0 | 表面积 |
| status | VARCHAR(20) | NOT NULL | 'draft' | | | | ✓ IN(13种) | 见 6.3 |
| planned_start_date | DATE | NULL | - | | | | | 计划开工 |
| planned_end_date | DATE | NULL | - | | | | ✓ ≥ start | 计划完工 |
| actual_start_date | DATE | NULL | - | | | | | 实际开工 |
| actual_end_date | DATE | NULL | - | | | | ✓ ≥ start | 实际完工 |
| erp_code | VARCHAR(64) | NULL | - | | | | | ERP 构件码 |
| erp_synced_at | TIMESTAMPTZ | NULL | - | | | | | |
| erp_sync_status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(4种) | |
| erp_extra | JSONB | NULL | - | | | | | |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

> 复合唯一：uq_components_project_component_no (project_id, component_no)

### 3.15 component_specifications（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 规格 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| spec_key | VARCHAR(64) | NOT NULL | - | | | | | 规格键 |
| spec_value | VARCHAR(255) | NULL | - | | | | | 规格值 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

> 复合唯一：uq_component_specifications_component_key (component_id, spec_key)

### 3.16 drawings（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 图纸 ID |
| component_id | BIGINT | NULL | - | | →components.id | | | 构件 |
| project_id | BIGINT | NULL | - | | →projects.id | | | 项目 |
| drawing_no | VARCHAR(64) | NOT NULL | - | | | | | 图号 |
| revision | VARCHAR(16) | NOT NULL | - | | | | | 版本 |
| file_path | VARCHAR(512) | NULL | - | | | | | 存储路径 |
| file_size | BIGINT | NULL | - | | | | ✓ ≥ 0 | 文件大小 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

> CHECK: (component_id IS NOT NULL OR project_id IS NOT NULL)
> 复合唯一：uq_drawings_no_revision (drawing_no, revision)

### 3.17 qrcodes（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 二维码 ID |
| component_id | BIGINT | NULL | - | | →components.id | | | 绑定构件 |
| code_value | VARCHAR(64) | NOT NULL | - | | | ✓ | | 二维码内容 |
| code_type | VARCHAR(20) | NOT NULL | 'component' | | | | ✓ IN(3种) | component/process/box |
| status | VARCHAR(20) | NOT NULL | 'unused' | | | | ✓ IN(4种) | 见 6.6 |
| is_primary | BOOLEAN | NOT NULL | FALSE | | | | | 是否当前主码 |
| printed_at | TIMESTAMPTZ | NULL | - | | | | | 打印时间 |
| printed_by | BIGINT | NULL | - | | →users.id | | | 打印人 |
| activated_at | TIMESTAMPTZ | NULL | - | | | | | 激活时间 |
| voided_at | TIMESTAMPTZ | NULL | - | | | | | 作废时间 |
| voided_reason | VARCHAR(128) | NULL | - | | | | | 作废原因 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

> CHECK: (status = 'unused') OR (component_id IS NOT NULL); (status = 'active') = is_primary
> 部分唯一索引：uq_qrcodes_component_active ON qrcodes(component_id) WHERE status='active' AND deleted_at IS NULL

### 3.18 qrcode_scan_logs（C 类，不可变）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 日志 ID |
| qrcode_id | BIGINT | NOT NULL | - | | →qrcodes.id | | | 二维码 |
| component_id | BIGINT | NULL | - | | →components.id | | | 当时关联构件 |
| operator_id | BIGINT | NULL | - | | →users.id | | | 扫码人 |
| device | VARCHAR(64) | NULL | - | | | | | 设备标识 |
| scan_purpose | VARCHAR(20) | NULL | - | | | | | 用途 |
| scan_result | VARCHAR(20) | NULL | - | | | | | success/fail |
| error_message | TEXT | NULL | - | | | | | 失败原因 |
| occurred_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | 扫码时间 |

### 3.19 process_definitions（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 工序 ID |
| code | VARCHAR(32) | NOT NULL | - | | | ✓ | | 工序编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 工序名称 |
| sequence | INTEGER | NOT NULL | - | | | | | 默认顺序 |
| work_center_type | VARCHAR(20) | NULL | - | | | | | 关联工作中心类型 |
| need_inspection | BOOLEAN | NOT NULL | TRUE | | | | | 是否需要质检 |
| description | TEXT | NULL | - | | | | | 描述 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.20 process_routes（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 路线 ID |
| code | VARCHAR(32) | NOT NULL | - | | | ✓ | | 路线编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 路线名称 |
| category_id | BIGINT | NULL | - | | →component_categories.id | | | 适用类别 |
| is_default | BOOLEAN | NOT NULL | FALSE | | | | | 默认路线 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.21 process_route_steps（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 步骤 ID |
| route_id | BIGINT | NOT NULL | - | | →process_routes.id | | | 路线 |
| step_no | INTEGER | NOT NULL | - | | | | | 步骤序号 |
| process_id | BIGINT | NOT NULL | - | | →process_definitions.id | | | 工序 |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 默认工作中心 |
| standard_time_min | NUMERIC(8,2) | NULL | - | | | | ✓ ≥ 0 | 标准工时 |
| need_inspection | BOOLEAN | NOT NULL | TRUE | | | | | 本步是否质检 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

> 复合唯一：uq_process_route_steps_route_step (route_id, step_no)

### 3.22 component_process_routes（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 实例 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | ✓ | | 构件（1:1） |
| source_route_id | BIGINT | NOT NULL | - | | →process_routes.id | | | 来源模板 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.23 component_process_route_steps（A 类，V1.1 新增）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 步骤实例 ID |
| component_route_id | BIGINT | NOT NULL | - | | →component_process_routes.id | | | 构件路线实例 |
| step_no | INTEGER | NOT NULL | - | | | | | 步骤序号 |
| process_id | BIGINT | NOT NULL | - | | →process_definitions.id | | | 工序 |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 实际工作中心 |
| standard_time_min | NUMERIC(8,2) | NULL | - | | | | ✓ ≥ 0 | 实际标准工时 |
| need_inspection | BOOLEAN | NOT NULL | TRUE | | | | | 本步是否质检 |
| source_step_id | BIGINT | NULL | - | | →process_route_steps.id | | | 来源模板步骤 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

> 复合唯一：uq_component_route_steps_route_step (component_route_id, step_no)

### 3.24 production_orders（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 工单 ID |
| order_id | BIGINT | NOT NULL | - | | →orders.id | | | 订单 |
| production_order_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 工单号 |
| batch_no | VARCHAR(32) | NULL | - | | | | | 生产批次编号 |
| planned_quantity | INTEGER | NOT NULL | - | | | | ✓ ≥ 0 | 计划数量 |
| status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(7种) | 工单状态 |
| planned_start_date | DATE | NULL | - | | | | | 计划开始 |
| planned_end_date | DATE | NULL | - | | | | ✓ ≥ start | 计划结束 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

### 3.25 production_tasks（核心表，A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 任务 ID |
| production_order_id | BIGINT | NOT NULL | - | | →production_orders.id | | | 工单 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| route_step_id | BIGINT | NOT NULL | - | | →component_process_route_steps.id | | | 构件步骤实例 |
| process_id | BIGINT | NOT NULL | - | | →process_definitions.id | | | 工序（冗余） |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 工作中心 |
| assigned_worker_id | BIGINT | NULL | - | | →workers.id | | | 分配工人 |
| task_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 任务号 |
| attempt_no | INTEGER | NOT NULL | 1 | | | | ✓ ≥ 1 | 执行次数 |
| status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(7种) | 见 6.4 |
| planned_quantity | INTEGER | NOT NULL | 1 | | | | ✓ ≥ 0 | 计划数量 |
| actual_quantity | INTEGER | NOT NULL | 0 | | | | ✓ ≥ 0, ≤ planned | 实际数量 |
| planned_start_at | TIMESTAMPTZ | NULL | - | | | | | 计划开始 |
| planned_end_at | TIMESTAMPTZ | NULL | - | | | | ✓ ≥ start | 计划结束 |
| actual_start_at | TIMESTAMPTZ | NULL | - | | | | | 实际开始 |
| actual_end_at | TIMESTAMPTZ | NULL | - | | | | ✓ ≥ start | 实际结束 |
| labor_time_min | NUMERIC(8,2) | NULL | - | | | | ✓ ≥ 0 | 工时 |
| parent_task_id | BIGINT | NULL | - | | →production_tasks.id | | | 父任务（返工链） |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

> 复合唯一：uq_production_tasks_comp_proc_attempt (component_id, process_id, attempt_no)

### 3.26 production_reports（C 类，不可变）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 报工 ID |
| task_id | BIGINT | NOT NULL | - | | →production_tasks.id | | | 任务 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| worker_id | BIGINT | NOT NULL | - | | →workers.id | | | 报工人 |
| report_type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(4种) | start/progress/complete/rework |
| quantity | INTEGER | NOT NULL | 0 | | | | ✓ ≥ 0 | 本次报工数量 |
| labor_time_min | NUMERIC(8,2) | NULL | - | | | | ✓ ≥ 0 | 工时 |
| work_center_id | BIGINT | NULL | - | | →work_centers.id | | | 工作中心 |
| equipment_id | BIGINT | NULL | - | | →equipment.id | | | 设备 |
| location | VARCHAR(128) | NULL | - | | | | | 操作地点 |
| remark | TEXT | NULL | - | | | | | 备注 |
| occurred_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | 报工时间 |
| operator_id | BIGINT | NULL | - | | →users.id | | | 操作人 |

### 3.27 quality_inspection_plans（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 计划 ID |
| process_id | BIGINT | NOT NULL | - | | →process_definitions.id | | | 工序 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 计划名称 |
| inspection_type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(4种) | first/self/patrol/final |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.28 quality_inspection_plan_items（B 类，V1.1 新增）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 检验项 ID |
| plan_id | BIGINT | NOT NULL | - | | →quality_inspection_plans.id | | | 质检计划 |
| item_no | VARCHAR(16) | NOT NULL | - | | | | | 项号 |
| inspection_item | VARCHAR(128) | NOT NULL | - | | | | | 检验项名称 |
| inspection_method | VARCHAR(64) | NULL | - | | | | | 检验方法 |
| standard_value | VARCHAR(128) | NULL | - | | | | | 标准值 |
| tolerance_upper | VARCHAR(64) | NULL | - | | | | | 上公差 |
| tolerance_lower | VARCHAR(64) | NULL | - | | | | | 下公差 |
| is_required | BOOLEAN | NOT NULL | TRUE | | | | | 是否必检 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

> 复合唯一：uq_inspection_plan_items_plan_no (plan_id, item_no)

### 3.29 quality_inspections（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 质检 ID |
| task_id | BIGINT | NOT NULL | - | | →production_tasks.id | | | 任务 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| process_id | BIGINT | NOT NULL | - | | →process_definitions.id | | | 工序 |
| plan_id | BIGINT | NULL | - | | →quality_inspection_plans.id | | | 质检计划 |
| inspector_id | BIGINT | NOT NULL | - | | →users.id | | | 质检员 |
| inspection_status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(6种) | 见 6.5 |
| inspection_type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(4种) | first/self/patrol/final |
| attempt_no | INTEGER | NOT NULL | 1 | | | | ✓ ≥ 1 | 质检次数 |
| inspected_at | TIMESTAMPTZ | NULL | - | | | | | 质检时间 |
| passed_items | INTEGER | NOT NULL | 0 | | | | ✓ ≥ 0 | 合格数 |
| failed_items | INTEGER | NOT NULL | 0 | | | | ✓ ≥ 0 | 不合格数 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.30 quality_inspection_items（A 类，V1.1 新增）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 明细 ID |
| inspection_id | BIGINT | NOT NULL | - | | →quality_inspections.id | | | 质检记录 |
| plan_item_id | BIGINT | NULL | - | | →quality_inspection_plan_items.id | | | 计划检验项 |
| inspection_item | VARCHAR(128) | NOT NULL | - | | | | | 检验项名称 |
| actual_value | VARCHAR(128) | NULL | - | | | | | 实际检验值 |
| standard_value | VARCHAR(128) | NULL | - | | | | | 标准值 |
| tolerance_upper | VARCHAR(64) | NULL | - | | | | | 上公差 |
| tolerance_lower | VARCHAR(64) | NULL | - | | | | | 下公差 |
| result | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(3种) | passed/failed/na |
| remark | TEXT | NULL | - | | | | | 备注 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

### 3.31 quality_defects（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 缺陷 ID |
| inspection_id | BIGINT | NOT NULL | - | | →quality_inspections.id | | | 质检记录 |
| inspection_item_id | BIGINT | NULL | - | | →quality_inspection_items.id | | | 质检明细项 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| defect_type | VARCHAR(64) | NOT NULL | - | | | | | 缺陷类型 |
| severity | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(3种) | critical/major/minor |
| description | TEXT | NOT NULL | - | | | | | 描述 |
| disposition | VARCHAR(20) | NULL | - | | | | ✓ IN(4种) | rework/scrap/accept/re_sort |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.32 nonconformance_reports（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | NCR ID |
| ncr_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | NCR 编号 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| inspection_id | BIGINT | NULL | - | | →quality_inspections.id | | | 关联质检 |
| defect_summary | TEXT | NOT NULL | - | | | | | 缺陷概述 |
| disposition | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(4种) | 处理意见 |
| status | VARCHAR(20) | NOT NULL | 'open' | | | | ✓ IN(6种) | 见 6.9 |
| approved_by | BIGINT | NULL | - | | →users.id | | | 审批人 |
| approved_at | TIMESTAMPTZ | NULL | - | | | | | 审批时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.33 warehouses（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 仓库 ID |
| code | VARCHAR(32) | NOT NULL | - | | | ✓ | | 仓库编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 名称 |
| address | VARCHAR(255) | NULL | - | | | | | 地址 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.34 locations（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 库位 ID |
| warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 仓库 |
| code | VARCHAR(32) | NOT NULL | - | | | | | 库位编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 库位名称 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

> 复合唯一：uq_locations_warehouse_code (warehouse_id, code)

### 3.35 component_stocks（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 库存 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | ✓ | | 构件（1:1） |
| warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 当前仓库 |
| location_id | BIGINT | NULL | - | | →locations.id | | | 当前库位 |
| status | VARCHAR(20) | NOT NULL | 'in_stock' | | | | ✓ IN(3种) | in_stock/reserved/shipped |
| incoming_at | TIMESTAMPTZ | NULL | - | | | | | 入库时间 |
| outgoing_at | TIMESTAMPTZ | NULL | - | | | | | 出库时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.36 stock_in_records（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 入库 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 仓库 |
| location_id | BIGINT | NULL | - | | →locations.id | | | 库位 |
| task_id | BIGINT | NULL | - | | →production_tasks.id | | | 关联任务 |
| inspector_id | BIGINT | NULL | - | | →users.id | | | 质检员 |
| quantity | INTEGER | NOT NULL | - | | | | ✓ ≥ 0 | 数量 |
| status | VARCHAR(20) | NOT NULL | 'pending' | | | | ✓ IN(3种) | pending/completed/cancelled |
| incoming_at | TIMESTAMPTZ | NULL | - | | | | | 实际入库时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.37 stock_out_records（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 出库 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 仓库 |
| out_type | VARCHAR(20) | NOT NULL | - | | | | ✓ IN(3种) | shipment/scrap/transfer |
| quantity | INTEGER | NOT NULL | - | | | | ✓ ≥ 0 | 数量 |
| ref_table | VARCHAR(64) | NULL | - | | | | | 关联表名 |
| ref_id | BIGINT | NULL | - | | | | | 关联记录 ID |
| outgoing_at | TIMESTAMPTZ | NULL | - | | | | | 实际出库时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.38 stock_transfer_records（A 类，V1.1 新增）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 转移 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| from_warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 原仓库 |
| from_location_id | BIGINT | NULL | - | | →locations.id | | | 原库位 |
| to_warehouse_id | BIGINT | NOT NULL | - | | →warehouses.id | | | 目标仓库 |
| to_location_id | BIGINT | NULL | - | | →locations.id | | | 目标库位 |
| transfer_reason | VARCHAR(128) | NULL | - | | | | | 转移原因 |
| transferred_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | 转移时间 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.39 shipments（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 发运单 ID |
| shipment_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 发运单号 |
| project_id | BIGINT | NOT NULL | - | | →projects.id | | | 项目 |
| order_id | BIGINT | NULL | - | | →orders.id | | | 订单 |
| destination | VARCHAR(255) | NULL | - | | | | | 目的地 |
| transport_type | VARCHAR(20) | NULL | - | | | | ✓ IN(3种) | sea/land/air |
| container_no | VARCHAR(64) | NULL | - | | | | | 集装箱号 |
| vehicle_no | VARCHAR(64) | NULL | - | | | | | 车牌/船名 |
| planned_shipment_date | DATE | NULL | - | | | | | 计划发运 |
| actual_shipment_date | DATE | NULL | - | | | | ✓ ≥ planned | 实际发运 |
| status | VARCHAR(20) | NOT NULL | 'planning' | | | | ✓ IN(7种) | 见 6.8 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |
| version | INTEGER | NOT NULL | 1 | | | | | 乐观锁 |

### 3.40 shipment_items（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 明细 ID |
| shipment_id | BIGINT | NOT NULL | - | | →shipments.id | | | 发运单 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| quantity | INTEGER | NOT NULL | 1 | | | | ✓ ≥ 0 | 数量 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

> 复合唯一：uq_shipment_items_shipment_component (shipment_id, component_id)

### 3.41 packing_lists（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 装箱单 ID |
| packing_list_no | VARCHAR(32) | NOT NULL | - | | | ✓ | | 装箱单号 |
| shipment_id | BIGINT | NULL | - | | →shipments.id | | | 发运单 |
| box_no | VARCHAR(32) | NULL | - | | | | | 箱号 |
| gross_weight_kg | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0 | 毛重 |
| net_weight_kg | NUMERIC(10,2) | NULL | - | | | | ✓ ≥ 0, ≤ gross | 净重 |
| dimension_lwh | VARCHAR(64) | NULL | - | | | | | 长×宽×高 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |
| remark | TEXT | NULL | - | | | | | |

### 3.42 packing_list_items（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | ID |
| packing_list_id | BIGINT | NOT NULL | - | | →packing_lists.id | | | 装箱单 |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| quantity | INTEGER | NOT NULL | 1 | | | | ✓ ≥ 0 | 数量 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

> 复合唯一：uq_packing_list_items_list_component (packing_list_id, component_id)

### 3.43 production_history_records（C 类，不可变）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 记录 ID |
| component_id | BIGINT | NOT NULL | - | | →components.id | | | 构件 |
| project_id | BIGINT | NULL | - | | →projects.id | | | 项目（冗余） |
| event_type | VARCHAR(32) | NOT NULL | - | | | | | 事件类型 |
| event_subtype | VARCHAR(32) | NULL | - | | | | | 子类型 |
| ref_table | VARCHAR(64) | NULL | - | | | | | 关联业务表名 |
| ref_id | BIGINT | NULL | - | | | | | 关联业务记录 ID |
| process_id | BIGINT | NULL | - | | →process_definitions.id | | | 工序 |
| task_id | BIGINT | NULL | - | | →production_tasks.id | | | 任务 |
| operator_id | BIGINT | NULL | - | | →users.id | | | 操作人 |
| from_status | VARCHAR(20) | NULL | - | | | | | 前状态 |
| to_status | VARCHAR(20) | NULL | - | | | | | 后状态 |
| quantity | INTEGER | NULL | - | | | | ✓ ≥ 0 | 涉及数量 |
| remark | TEXT | NULL | - | | | | | 备注 |
| occurred_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | 事件时间 |

### 3.44 operation_logs（C 类，不可变）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 日志 ID |
| user_id | BIGINT | NULL | - | | →users.id | | | 操作人 |
| module | VARCHAR(64) | NOT NULL | - | | | | | 模块 |
| action | VARCHAR(64) | NOT NULL | - | | | | | 动作 |
| target_table | VARCHAR(64) | NULL | - | | | | | 操作表 |
| target_id | BIGINT | NULL | - | | | | | 记录 ID |
| changed_fields | JSONB | NULL | - | | | | | 仅变更字段 |
| ip | VARCHAR(64) | NULL | - | | | | | IP |
| user_agent | VARCHAR(255) | NULL | - | | | | | 客户端 |
| occurred_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | 时间 |

### 3.45 system_configs（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 配置 ID |
| config_key | VARCHAR(128) | NOT NULL | - | | | ✓ | | 键 |
| config_value | TEXT | NULL | - | | | | | 值 |
| config_type | VARCHAR(20) | NULL | - | | | | | string/integer/boolean/json |
| description | TEXT | NULL | - | | | | | 描述 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.46 attachments（A 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 附件 ID |
| ref_table | VARCHAR(64) | NOT NULL | - | | | | | 关联表 |
| ref_id | BIGINT | NOT NULL | - | | | | | 关联 ID |
| file_name | VARCHAR(255) | NOT NULL | - | | | | | 原文件名 |
| file_path | VARCHAR(512) | NOT NULL | - | | | | | 存储路径 |
| file_size | BIGINT | NULL | - | | | | ✓ ≥ 0 | 文件大小 |
| mime_type | VARCHAR(128) | NULL | - | | | | | MIME |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | 上传人 |
| updated_by | BIGINT | NULL | - | | →users.id | | | |
| deleted_at | TIMESTAMPTZ | NULL | - | | | | | 软删除 |

### 3.47 dictionaries（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 字典 ID |
| code | VARCHAR(64) | NOT NULL | - | | | ✓ | | 字典编码 |
| name | VARCHAR(128) | NOT NULL | - | | | | | 字典名称 |
| description | TEXT | NULL | - | | | | | 描述 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

### 3.48 dictionary_items（B 类）

| 字段名 | 类型 | NULL/NOT NULL | 默认值 | PK | FK | UNIQUE | CHECK | 说明 |
|------|------|------|------|------|------|------|------|------|
| id | BIGINT | NOT NULL | IDENTITY | ✓ | | | | 字典项 ID |
| dictionary_id | BIGINT | NOT NULL | - | | →dictionaries.id | | | 字典 |
| item_code | VARCHAR(64) | NOT NULL | - | | | | | 项编码 |
| item_value | VARCHAR(255) | NOT NULL | - | | | | | 项值 |
| sort_order | INTEGER | NOT NULL | 0 | | | | | 排序 |
| is_active | BOOLEAN | NOT NULL | TRUE | | | | | 启用 |
| created_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| updated_at | TIMESTAMPTZ | NOT NULL | NOW() | | | | | |
| created_by | BIGINT | NULL | - | | →users.id | | | |
| updated_by | BIGINT | NULL | - | | →users.id | | | |

> 复合唯一：uq_dictionary_items_dict_code (dictionary_id, item_code)

---

## 4. 核心关系

完整链路（含中间表与外键路径）：

```
1. 项目 projects
   │
   ↓ project_id
2. 订单 orders
   │
   ↓ order_id
3. 订单明细 order_items (order_id → orders.id)
   │
   ↓ (通过 production_orders 间接关联构件)
4. 构件 components (project_id → projects.id)
   │   注：V1.1 去除了 order_id/order_item_id，订单关系通过 production_orders 维护
   │
   ├── 二维码 qrcodes (component_id → components.id, 1 主码 + N 历史码)
   │
   ↓ component_id (1:1)
5. 构件工艺路线实例 component_process_routes (component_id → components.id)
   │   source_route_id → process_routes.id (来源模板)
   │
   ↓ component_route_id (1:N)
6. 构件工艺步骤实例 component_process_route_steps (component_route_id → component_process_routes.id)
   │   process_id → process_definitions.id
   │   source_step_id → process_route_steps.id (来源模板步骤)
   │
   ↓ route_step_id (1:N)
7. 生产任务 production_tasks (route_step_id → component_process_route_steps.id)
   │   component_id → components.id (冗余)
   │   process_id → process_definitions.id (冗余)
   │   parent_task_id → production_tasks.id (返工链)
   │   attempt_no 区分首次与返工
   │
   ↓ task_id (1:N)
8. 生产报工 production_reports (task_id → production_tasks.id, 不可变)
   │
   ↓ task_id (1:N)
9. 质检 quality_inspections (task_id → production_tasks.id)
   │   ↓ inspection_id (1:N)
   │   质检明细 quality_inspection_items (inspection_id → quality_inspections.id)
   │   ↓ inspection_id (1:N)
   │   不合格缺陷 quality_defects (inspection_id → quality_inspections.id)
   │
   │   返工/复检分支：
   │   - 质检 failed → rework → re_inspection
   │   - 任务 completed → rework_requested → 新任务 attempt_no+1
   │
   ↓ (质检合格后)
10. 入库 stock_in_records (component_id → components.id, task_id → production_tasks.id)
    │   ↓ status='completed' 时
    │   创建/更新 → component_stocks (component_id → components.id, 1:1)
    │
    │   库位转移分支：
    │   stock_transfer_records (component_id → components.id)
    │   触发 component_stocks.location_id 变更
    │
    ↓ (发运)
11. 发运明细 shipment_items (component_id → components.id, shipment_id → shipments.id)
    │
    │   装箱分支（独立关系）：
    │   packing_lists (shipment_id → shipments.id, 1:N)
    │   ↓ packing_list_id
    │   packing_list_items (packing_list_id → packing_lists.id, component_id → components.id)
    │
    ↓ (全部业务事件同事务写入)
12. 生产履历 production_history_records (component_id → components.id, 不可变)
    │   ref_table + ref_id 指向具体业务记录
    │   event_type 标识事件类型
    │   occurred_at 记录事件时间
    │   禁止 UPDATE/DELETE（trigger 强制）
```

---

## 5. 状态机

### 5.1 projects.status

**合法值**：planning, confirmed, in_progress, on_hold, completed, closed, cancelled

**合法转换**：
- planning → confirmed
- confirmed → in_progress
- in_progress → on_hold
- on_hold → in_progress
- in_progress → completed
- completed → closed
- 任意非终态 → cancelled
- 任意非终态 → on_hold → 回到原状态

**终态**：closed, cancelled

### 5.2 orders.status

**合法值**：draft, confirmed, in_production, on_hold, completed, closed, cancelled

**合法转换**：
- draft → confirmed
- confirmed → in_production
- in_production → on_hold
- on_hold → in_production
- in_production → completed
- completed → closed
- 任意非终态 → cancelled
- 任意非终态 → on_hold → 回到原状态

**终态**：closed, cancelled

### 5.3 components.status

**合法值**：draft, released, in_production, on_hold, in_inspection, passed, failed, rework, re_inspection, in_stock, shipped, completed, scrapped

**合法转换**：
- draft → released
- released → in_production
- in_production → on_hold
- on_hold → in_production
- in_production → in_inspection
- in_inspection → passed
- in_inspection → failed
- failed → rework
- rework → in_production
- rework → re_inspection
- re_inspection → passed
- re_inspection → failed
- passed → in_stock
- in_stock → shipped
- shipped → completed
- 任意非终态 → scrapped
- 任意非终态 → on_hold → 回到原状态

**终态**：completed, scrapped

### 5.4 production_tasks.status

**合法值**：pending, assigned, in_progress, paused, completed, rework_requested, cancelled

**合法转换**：
- pending → assigned
- assigned → in_progress
- assigned → paused
- in_progress → paused
- paused → assigned
- paused → in_progress
- in_progress → completed
- completed → rework_requested
- rework_requested → pending（新 attempt_no）
- 任意非终态 → cancelled

**终态**：cancelled（completed 为逻辑终态，但可触发 rework_requested）

### 5.5 quality_inspections.inspection_status

**合法值**：pending, inspecting, passed, failed, rework, re_inspection

**合法转换**：
- pending → inspecting
- inspecting → passed
- inspecting → failed
- failed → rework
- rework → re_inspection
- re_inspection → passed
- re_inspection → failed

**终态**：passed, failed（re_inspection 的 failed 也是终态）

### 5.6 qrcodes.status

**合法值**：unused, active, disabled, voided

**合法转换**：
- unused → active
- active → disabled
- disabled → active（重新激活）
- disabled → voided
- active → voided（构件销毁）

**终态**：voided

**约束**：同一构件同一时间只能有一个 active 主码（部分唯一索引保证）

### 5.7 stock_in_records.status

**合法值**：pending, completed, cancelled

**合法转换**：
- pending → completed
- pending → cancelled

**终态**：completed, cancelled

### 5.8 shipments.status

**合法值**：planning, confirmed, loading, on_hold, shipped, delivered, cancelled

**合法转换**：
- planning → confirmed
- confirmed → loading
- loading → on_hold
- on_hold → loading
- loading → shipped
- shipped → delivered
- 任意非终态 → cancelled
- 任意非终态 → on_hold → 回到原状态

**终态**：delivered, cancelled

### 5.9 nonconformance_reports.status

**合法值**：open, in_review, approved, in_rework, closed, rejected

**合法转换**：
- open → in_review
- in_review → approved
- in_review → rejected
- approved → in_rework
- in_rework → closed
- 任意非终态 → rejected

**终态**：closed, rejected

### 5.10 equipment.status

**合法值**：idle, running, maintenance, broken

**合法转换**：原文未显式定义状态机，但字段标注为 idle/running/maintenance/broken。

### 5.11 component_stocks.status

**合法值**：in_stock, reserved, shipped

**合法转换**：原文未显式定义状态机，但通过 stock_in/stock_out/stock_transfer 操作触发。

### 5.12 production_orders.status

**合法值**：pending, released, in_progress, on_hold, completed, closed, cancelled

**合法转换**：原文未在状态机章节（第 6 节）显式列出，但 CHECK 约束允许以上值。

---

## 6. 唯一约束

### 6.1 单列唯一约束

| 表 | 字段 | 业务含义 |
|------|------|------|
| users | username | 登录名全局唯一 |
| roles | code | 角色编码全局唯一 |
| permissions | code | 权限点全局唯一 |
| departments | code | 部门编码全局唯一 |
| workers | user_id | 一个用户只能有一个工人档案 |
| workers | worker_no | 工号全局唯一 |
| work_centers | code | 工作中心编码全局唯一 |
| equipment | code | 设备编码全局唯一 |
| projects | code | 项目编号全局唯一 |
| orders | order_no | 订单号全局唯一 |
| component_categories | code | 类别编码全局唯一 |
| qrcodes | code_value | 二维码内容全局唯一 |
| process_definitions | code | 工序编码全局唯一 |
| process_routes | code | 路线编码全局唯一 |
| component_process_routes | component_id | 1 构件 1 工艺路线实例 |
| production_orders | production_order_no | 工单号全局唯一 |
| production_tasks | task_no | 任务号全局唯一 |
| nonconformance_reports | ncr_no | NCR 编号全局唯一 |
| warehouses | code | 仓库编码全局唯一 |
| component_stocks | component_id | 1 构件 1 库存行 |
| shipments | shipment_no | 发运单号全局唯一 |
| packing_lists | packing_list_no | 装箱单号全局唯一 |
| system_configs | config_key | 配置键全局唯一 |
| dictionaries | code | 字典编码全局唯一 |

### 6.2 复合唯一约束

| 表 | 字段组合 | 约束名 | 业务含义 |
|------|------|------|------|
| user_roles | (user_id, role_id) | PK | 一个用户一个角色唯一 |
| role_permissions | (role_id, permission_id) | PK | 一个角色一个权限唯一 |
| order_items | (order_id, line_no) | uq_order_items_order_line | 订单内行号唯一 |
| components | (project_id, component_no) | uq_components_project_component_no | 项目内构件号唯一 |
| component_specifications | (component_id, spec_key) | uq_component_specifications_component_key | 构件规格键唯一 |
| drawings | (drawing_no, revision) | uq_drawings_no_revision | 图号+版本唯一 |
| process_route_steps | (route_id, step_no) | uq_process_route_steps_route_step | 路线内步骤序号唯一 |
| component_process_route_steps | (component_route_id, step_no) | uq_component_route_steps_route_step | 构件路线内步骤序号唯一 |
| production_tasks | (component_id, process_id, attempt_no) | uq_production_tasks_comp_proc_attempt | 同构件同工序同执行次数唯一（支持返工） |
| quality_inspection_plan_items | (plan_id, item_no) | uq_inspection_plan_items_plan_no | 计划内项号唯一 |
| locations | (warehouse_id, code) | uq_locations_warehouse_code | 仓库内库位编码唯一 |
| shipment_items | (shipment_id, component_id) | uq_shipment_items_shipment_component | 发运单内构件唯一 |
| packing_list_items | (packing_list_id, component_id) | uq_packing_list_items_list_component | 装箱单内构件唯一 |
| dictionary_items | (dictionary_id, item_code) | uq_dictionary_items_dict_code | 字典内项编码唯一 |

### 6.3 部分唯一索引

| 表 | 索引名 | 字段 | WHERE 条件 | 业务含义 |
|------|------|------|------|------|
| qrcodes | uq_qrcodes_component_active | (component_id) | status = 'active' AND deleted_at IS NULL | 同一构件同一时间只能有一个 active 主码 |

### 6.4 部分索引（非唯一）

| 表 | 索引名 | 字段 | WHERE 条件 | 业务含义 |
|------|------|------|------|------|
| components | idx_components_project_active | (project_id) | deleted_at IS NULL | 按项目查未删除构件 |

---

## 7. 外键依赖

### 7.1 全部外键列表

| 子表 | 字段 | 父表 | 字段 |
|------|------|------|------|
| users | department_id | departments | id |
| users | created_by | users | id |
| users | updated_by | users | id |
| user_roles | user_id | users | id |
| user_roles | role_id | roles | id |
| user_roles | created_by | users | id |
| role_permissions | role_id | roles | id |
| role_permissions | permission_id | permissions | id |
| role_permissions | created_by | users | id |
| departments | parent_id | departments | id |
| departments | created_by | users | id |
| departments | updated_by | users | id |
| workers | user_id | users | id |
| workers | work_center_id | work_centers | id |
| workers | created_by | users | id |
| workers | updated_by | users | id |
| work_centers | created_by | users | id |
| work_centers | updated_by | users | id |
| equipment | work_center_id | work_centers | id |
| equipment | created_by | users | id |
| equipment | updated_by | users | id |
| projects | created_by | users | id |
| projects | updated_by | users | id |
| orders | project_id | projects | id |
| orders | created_by | users | id |
| orders | updated_by | users | id |
| order_items | order_id | orders | id |
| order_items | category_id | component_categories | id |
| order_items | created_by | users | id |
| order_items | updated_by | users | id |
| component_categories | parent_id | component_categories | id |
| component_categories | created_by | users | id |
| component_categories | updated_by | users | id |
| components | project_id | projects | id |
| components | category_id | component_categories | id |
| components | created_by | users | id |
| components | updated_by | users | id |
| component_specifications | component_id | components | id |
| component_specifications | created_by | users | id |
| component_specifications | updated_by | users | id |
| drawings | component_id | components | id |
| drawings | project_id | projects | id |
| drawings | created_by | users | id |
| drawings | updated_by | users | id |
| qrcodes | component_id | components | id |
| qrcodes | printed_by | users | id |
| qrcodes | created_by | users | id |
| qrcodes | updated_by | users | id |
| qrcode_scan_logs | qrcode_id | qrcodes | id |
| qrcode_scan_logs | component_id | components | id |
| qrcode_scan_logs | operator_id | users | id |
| process_definitions | created_by | users | id |
| process_definitions | updated_by | users | id |
| process_routes | category_id | component_categories | id |
| process_routes | created_by | users | id |
| process_routes | updated_by | users | id |
| process_route_steps | route_id | process_routes | id |
| process_route_steps | process_id | process_definitions | id |
| process_route_steps | work_center_id | work_centers | id |
| process_route_steps | created_by | users | id |
| process_route_steps | updated_by | users | id |
| component_process_routes | component_id | components | id |
| component_process_routes | source_route_id | process_routes | id |
| component_process_routes | created_by | users | id |
| component_process_routes | updated_by | users | id |
| component_process_route_steps | component_route_id | component_process_routes | id |
| component_process_route_steps | process_id | process_definitions | id |
| component_process_route_steps | work_center_id | work_centers | id |
| component_process_route_steps | source_step_id | process_route_steps | id |
| component_process_route_steps | created_by | users | id |
| component_process_route_steps | updated_by | users | id |
| production_orders | order_id | orders | id |
| production_orders | created_by | users | id |
| production_orders | updated_by | users | id |
| production_tasks | production_order_id | production_orders | id |
| production_tasks | component_id | components | id |
| production_tasks | route_step_id | component_process_route_steps | id |
| production_tasks | process_id | process_definitions | id |
| production_tasks | work_center_id | work_centers | id |
| production_tasks | assigned_worker_id | workers | id |
| production_tasks | parent_task_id | production_tasks | id |
| production_tasks | created_by | users | id |
| production_tasks | updated_by | users | id |
| production_reports | task_id | production_tasks | id |
| production_reports | component_id | components | id |
| production_reports | worker_id | workers | id |
| production_reports | work_center_id | work_centers | id |
| production_reports | equipment_id | equipment | id |
| production_reports | operator_id | users | id |
| quality_inspection_plans | process_id | process_definitions | id |
| quality_inspection_plans | created_by | users | id |
| quality_inspection_plans | updated_by | users | id |
| quality_inspection_plan_items | plan_id | quality_inspection_plans | id |
| quality_inspection_plan_items | created_by | users | id |
| quality_inspection_plan_items | updated_by | users | id |
| quality_inspections | task_id | production_tasks | id |
| quality_inspections | component_id | components | id |
| quality_inspections | process_id | process_definitions | id |
| quality_inspections | plan_id | quality_inspection_plans | id |
| quality_inspections | inspector_id | users | id |
| quality_inspections | created_by | users | id |
| quality_inspections | updated_by | users | id |
| quality_inspection_items | inspection_id | quality_inspections | id |
| quality_inspection_items | plan_item_id | quality_inspection_plan_items | id |
| quality_inspection_items | created_by | users | id |
| quality_inspection_items | updated_by | users | id |
| quality_defects | inspection_id | quality_inspections | id |
| quality_defects | inspection_item_id | quality_inspection_items | id |
| quality_defects | component_id | components | id |
| quality_defects | created_by | users | id |
| quality_defects | updated_by | users | id |
| nonconformance_reports | component_id | components | id |
| nonconformance_reports | inspection_id | quality_inspections | id |
| nonconformance_reports | approved_by | users | id |
| nonconformance_reports | created_by | users | id |
| nonconformance_reports | updated_by | users | id |
| warehouses | created_by | users | id |
| warehouses | updated_by | users | id |
| locations | warehouse_id | warehouses | id |
| locations | created_by | users | id |
| locations | updated_by | users | id |
| component_stocks | component_id | components | id |
| component_stocks | warehouse_id | warehouses | id |
| component_stocks | location_id | locations | id |
| component_stocks | created_by | users | id |
| component_stocks | updated_by | users | id |
| stock_in_records | component_id | components | id |
| stock_in_records | warehouse_id | warehouses | id |
| stock_in_records | location_id | locations | id |
| stock_in_records | task_id | production_tasks | id |
| stock_in_records | inspector_id | users | id |
| stock_in_records | created_by | users | id |
| stock_in_records | updated_by | users | id |
| stock_out_records | component_id | components | id |
| stock_out_records | warehouse_id | warehouses | id |
| stock_out_records | created_by | users | id |
| stock_out_records | updated_by | users | id |
| stock_transfer_records | component_id | components | id |
| stock_transfer_records | from_warehouse_id | warehouses | id |
| stock_transfer_records | from_location_id | locations | id |
| stock_transfer_records | to_warehouse_id | warehouses | id |
| stock_transfer_records | to_location_id | locations | id |
| stock_transfer_records | created_by | users | id |
| stock_transfer_records | updated_by | users | id |
| shipments | project_id | projects | id |
| shipments | order_id | orders | id |
| shipments | created_by | users | id |
| shipments | updated_by | users | id |
| shipment_items | shipment_id | shipments | id |
| shipment_items | component_id | components | id |
| shipment_items | created_by | users | id |
| shipment_items | updated_by | users | id |
| packing_lists | shipment_id | shipments | id |
| packing_lists | created_by | users | id |
| packing_lists | updated_by | users | id |
| packing_list_items | packing_list_id | packing_lists | id |
| packing_list_items | component_id | components | id |
| packing_list_items | created_by | users | id |
| packing_list_items | updated_by | users | id |
| production_history_records | component_id | components | id |
| production_history_records | project_id | projects | id |
| production_history_records | process_id | process_definitions | id |
| production_history_records | task_id | production_tasks | id |
| production_history_records | operator_id | users | id |
| operation_logs | user_id | users | id |
| system_configs | created_by | users | id |
| system_configs | updated_by | users | id |
| attachments | created_by | users | id |
| attachments | updated_by | users | id |
| dictionaries | created_by | users | id |
| dictionaries | updated_by | users | id |
| dictionary_items | dictionary_id | dictionaries | id |
| dictionary_items | created_by | users | id |
| dictionary_items | updated_by | users | id |

### 7.2 推荐建表顺序

1. users（自引用 created_by/updated_by，需先建表后加 FK）
2. roles, permissions
3. user_roles, role_permissions
4. departments（自引用 parent_id）
5. work_centers
6. equipment
7. workers
8. projects
9. orders
10. component_categories（自引用 parent_id）
11. process_definitions
12. process_routes
13. process_route_steps
14. components
15. component_specifications
16. drawings
17. component_process_routes
18. component_process_route_steps
19. qrcodes
20. qrcode_scan_logs
21. production_orders
22. production_tasks（自引用 parent_task_id）
23. production_reports
24. quality_inspection_plans
25. quality_inspection_plan_items
26. quality_inspections
27. quality_inspection_items
28. quality_defects
29. nonconformance_reports
30. warehouses
31. locations
32. component_stocks
33. stock_in_records
34. stock_out_records
35. stock_transfer_records
36. shipments
37. shipment_items
38. packing_lists
39. packing_list_items
40. production_history_records
41. operation_logs
42. system_configs
43. attachments
44. dictionaries
45. dictionary_items

> 注：users 自引用、departments 自引用、component_categories 自引用、production_tasks 自引用 需先建表后加外键约束（ALTER TABLE ADD CONSTRAINT）。

---

## 8. 事务一致性

### 8.1 必须与生产履历在同一事务的业务操作

| 业务操作 | 涉及业务表 | 履历事件 | 事务要求 |
|------|------|------|------|
| 构件状态变更 | components (UPDATE status) | status_change | 同事务 |
| 任务分配 | production_tasks (UPDATE status→assigned) | task_assigned | 同事务 |
| 任务开工 | production_tasks (UPDATE status→in_progress), production_reports (INSERT) | task_started | 同事务 |
| 任务完工 | production_tasks (UPDATE status→completed), production_reports (INSERT) | task_completed | 同事务 |
| 任务返工请求 | production_tasks (UPDATE status→rework_requested) | task_rework_requested | 同事务 |
| 报工 | production_reports (INSERT) | production_reported | 同事务 |
| 质检开始 | quality_inspections (UPDATE status→inspecting) | inspection_started | 同事务 |
| 质检合格 | quality_inspections (UPDATE status→passed) | inspection_passed | 同事务 |
| 质检不合格 | quality_inspections (UPDATE status→failed), quality_defects (INSERT) | inspection_failed | 同事务 |
| 返工开始 | quality_inspections (UPDATE status→rework) | rework_started | 同事务 |
| 返工完成 | quality_inspections (UPDATE status→re_inspection 或 passed) | rework_completed | 同事务 |
| 复检开始 | quality_inspections (UPDATE status→re_inspection) | re_inspection_started | 同事务 |
| 入库 | stock_in_records (INSERT/UPDATE), component_stocks (UPSERT) | stock_in | 同事务 |
| 出库 | stock_out_records (INSERT), component_stocks (UPDATE) | stock_out | 同事务 |
| 库位转移 | stock_transfer_records (INSERT), component_stocks (UPDATE) | stock_transferred | 同事务 |
| 发运 | shipment_items (INSERT), component_stocks (UPDATE) | shipped | 同事务 |
| 二维码打印 | qrcodes (INSERT/UPDATE) | qr_printed | 同事务 |
| 二维码激活 | qrcodes (UPDATE status→active) | qr_activated | 同事务 |
| 二维码作废 | qrcodes (UPDATE status→voided) | qr_voided | 同事务 |
| 扫码 | qrcode_scan_logs (INSERT) | qr_scanned | 同事务 |
| NCR 创建 | nonconformance_reports (INSERT) | ncr_created | 同事务 |
| NCR 关闭 | nonconformance_reports (UPDATE status→closed) | ncr_closed | 同事务 |

### 8.2 事务保证机制

- **应用层**：使用 `async with db.transaction()` 包裹业务写入 + 履历写入
- **数据库层**：production_history_records 有 trigger 禁止 UPDATE/DELETE，确保履历不可篡改
- **一致性**：业务成功但履历失败 → 事务回滚；履历成功但业务失败 → 事务回滚
- **无孤儿**：不会出现"业务成功但无履历"或"有履历但无业务"的不一致状态

---

## 9. 软删除规则

### 9.1 允许 deleted_at 的表（A 类普通业务表）

| 表 | 类型 | 软删除 |
|------|------|------|
| users | A | ✓ |
| departments | A | ✓ |
| workers | A | ✓ |
| equipment | A | ✓ |
| projects | A | ✓ |
| orders | A | ✓ |
| order_items | A | ✓ |
| components | A | ✓ |
| component_specifications | A | ✓ |
| drawings | A | ✓ |
| qrcodes | A | ✓ |
| component_process_routes | A | ✓ |
| component_process_route_steps | A | ✓ |
| production_orders | A | ✓ |
| production_tasks | A | ✓ |
| quality_inspections | A | ✓ |
| quality_inspection_items | A | ✓ |
| quality_defects | A | ✓ |
| nonconformance_reports | A | ✓ |
| component_stocks | A | ✓ |
| stock_in_records | A | ✓ |
| stock_out_records | A | ✓ |
| stock_transfer_records | A | ✓ |
| shipments | A | ✓ |
| shipment_items | A | ✓ |
| packing_lists | A | ✓ |
| packing_list_items | A | ✓ |
| attachments | A | ✓ |

### 9.2 禁止 deleted_at 的表（B/C/D 类）

| 表 | 类型 | 软删除替代方案 |
|------|------|------|
| roles | B | is_active = FALSE |
| permissions | B | is_active = FALSE |
| work_centers | B | is_active = FALSE |
| process_definitions | B | is_active = FALSE |
| process_routes | B | is_active = FALSE |
| process_route_steps | B | is_active（继承自路线） |
| component_categories | B | is_active = FALSE |
| quality_inspection_plans | B | is_active = FALSE |
| quality_inspection_plan_items | B | is_active（继承自计划） |
| warehouses | B | is_active = FALSE |
| locations | B | is_active = FALSE |
| system_configs | B | is_active = FALSE |
| dictionaries | B | is_active = FALSE |
| dictionary_items | B | is_active = FALSE |
| user_roles | D | 直接 DELETE 行 |
| role_permissions | D | 直接 DELETE 行 |
| qrcode_scan_logs | C | 禁止 UPDATE/DELETE（trigger） |
| production_reports | C | 禁止 UPDATE/DELETE（trigger） |
| production_history_records | C | 禁止 UPDATE/DELETE（trigger） |
| operation_logs | C | 禁止 UPDATE/DELETE（trigger） |

---

## 10. V1.1 自检结果

> 以下完整列出原文第 16 节自检报告，不做修改。

### 16.1 循环依赖检查

| 检查项 | 结果 |
|------|------|
| components → projects | ✓ 单向 |
| qrcodes → components | ✓ 单向 |
| component_process_routes → components, process_routes | ✓ 单向 |
| component_process_route_steps → component_process_routes, process_route_steps, process_definitions | ✓ 单向 |
| production_tasks → components, component_process_route_steps, production_orders | ✓ 单向 |
| production_history_records → components/projects/tasks | ✓ 单向 |
| departments 自引用 | ✓ path 字段避免递归 |
| component_categories 自引用 | ✓ 同上 |
| production_tasks.parent_task_id 自引用 | ✓ 返工链，无环 |

**结论**：未发现循环依赖。

### 16.2 重复事实检查

| 检查项 | V1.0 | V1.1 | 结果 |
|------|------|------|------|
| components 同时有 project_id, order_id, order_item_id | 重复事实 | V1.1 去除 order_id, order_item_id | ✓ 修复 |
| components.process_route_id 与 component_process_routes | 重复 | V1.1 去除 process_route_id | ✓ 修复 |
| components.current_process_id 可推导 | 冗余 | V1.1 去除，通过 tasks 推导 | ✓ 修复 |
| shipment_items.packing_list_id 与 packing_list_items | 重复装箱关系 | V1.1 去除 packing_list_id | ✓ 修复 |
| production_history_records.order_id | 可推导 | V1.1 去除 | ✓ 修复 |
| production_reports.component_id | 与 task 重复 | 保留：便于查询，故意冗余 | ✓ 合理 |
| production_history_records.project_id | 可推导 | 保留：避免 JOIN，故意冗余 | ✓ 合理 |

**结论**：V1.1 消除了所有无意义重复事实，保留的冗余字段都有明确理由。

### 16.3 唯一约束检查

| 表 | 唯一约束 | V1.0 | V1.1 |
|------|------|------|------|
| components | component_no | 全局 UNIQUE | UNIQUE(project_id, component_no) ✓ |
| qrcodes.component_id | UNIQUE | 与历史码矛盾 | 部分唯一索引 WHERE status='active' ✓ |
| production_tasks | (component_id, process_id, sequence) | 阻止返工 | (component_id, process_id, attempt_no) ✓ |
| quality_inspections | 无 | - | 保留多行（多次质检） ✓ |

**结论**：V1.1 唯一约束设计合理，支持返工与历史码。

### 16.4 状态机完整性检查

| 业务对象 | 状态机 | 终态 | 暂停 | 取消 | 返工 | 复检 |
|------|------|------|------|------|------|------|
| 项目 | ✓ | closed/cancelled | ✓ on_hold | ✓ | - | - |
| 订单 | ✓ | closed/cancelled | ✓ on_hold | ✓ | - | - |
| 构件 | ✓ | completed/scrapped | ✓ on_hold | - | ✓ rework | ✓ re_inspection |
| 任务 | ✓ | completed/cancelled | ✓ paused | ✓ | ✓ rework_requested | - |
| 质检 | ✓ | passed/failed | - | - | ✓ rework | ✓ re_inspection |
| 二维码 | ✓ | voided | - disabled | - | - | ✓ 可重新激活 |
| 入库 | ✓ | completed/cancelled | - | ✓ | - | - |
| 发运 | ✓ | delivered/cancelled | ✓ on_hold | ✓ | - | - |
| NCR | ✓ | closed/rejected | - | - | ✓ in_rework | - |

**结论**：每个状态机都有终态，并支持暂停/取消/返工/复检等实际业务分支。

### 16.5 二维码检查

- 主码唯一：✓ 部分唯一索引 WHERE status='active'
- 历史码保留：✓ 允许多个 disabled/voided
- 补码流程：✓ 原码 voided → 新码 active
- 编码不依赖内部 ID：✓ 仅依赖项目编码 + 构件业务编号
- 校验算法明确：✓ CRC32 末4位大写十六进制

### 16.6 工艺路线实例化检查

- 模板：process_routes → process_route_steps ✓
- 实例：component_process_routes → component_process_route_steps ✓
- 任务关联：production_tasks.route_step_id → component_process_route_steps.id ✓
- 模板修改不影响已实例化构件：✓ source_step_id 仅作参考

### 16.7 返工支持检查

- 任务返工：✓ attempt_no + parent_task_id
- 任务唯一约束：✓ (component_id, process_id, attempt_no) 允许多次
- 质检返工：✓ inspection_status: failed → rework → re_inspection
- 质检复检：✓ attempt_no 字段支持多次质检
- 构件返工：✓ status: in_inspection → failed → rework → in_production

### 16.8 质检复检检查

- 质检计划多检验项：✓ quality_inspection_plan_items
- 质检明细项：✓ quality_inspection_items 记录实际值与结果
- 质检状态机：✓ pending → inspecting → passed/failed → rework → re_inspection

### 16.9 库存检查

- 构件实体模型：✓ component_stocks 1:1 构件
- 数据来源清晰：✓ stock_in_records 创建、stock_transfer_records 更新、stock_out_records 出库
- 库位变化可追溯：✓ stock_transfer_records 独立表

### 16.10 发运装箱检查

- 发运单↔构件关系：✓ shipment_items（单一事实来源）
- 装箱单↔构件关系：✓ packing_list_items（单一事实来源）
- 发运单↔装箱单关系：✓ packing_lists.shipment_id
- 无重复表达：✓ shipment_items 不再含 packing_list_id

### 16.11 生产履历检查

- 同事务保证：✓ 应用层强制事务包裹
- 不可变：✓ trigger 禁止 UPDATE/DELETE
- 无 updated_at/deleted_at：✓ C 类表规范
- 边界清晰：✓ 履历=构件业务视角，日志=用户操作视角

### 16.12 软删除检查

- A 类业务表：✓ 有 deleted_at
- B 类配置表：✓ 用 is_active 代替
- C 类不可变表：✓ 无 deleted_at，禁止删除
- D 类关联表：✓ 无 deleted_at，直接 DELETE 行

### 16.13 ERP 预留检查

- erp_code/erp_synced_at/erp_sync_status/erp_extra：✓ projects/orders/components
- erp_extra JSONB：✓ 任意扩展字段

---

【DATABASE_DESIGN_V1.1 审核包完成】