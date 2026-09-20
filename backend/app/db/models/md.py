"""md schema — Layer 2 projects / organization / RBAC / master data (18 A-class tables).

Design doc: database_design_v1.2.md chapter 3.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, AMasterDataMixin, Base, TableBase
from app.db.enums import enum_project, enum_membership

SCHEMA = "md"


class MainProject(TableBase, ALifecycleMixin):
    """3.1 主项目；八态状态机 + aud.project_status_history 留痕（服务层）。"""
    __tablename__ = "main_project"
    __table_args__ = {"schema": SCHEMA}
    project_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(128))
    delivery_due: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(enum_project, nullable=False, server_default=text("'draft'"))


class Subproject(TableBase, ALifecycleMixin):
    """3.2 子项目；subproject_code 主项目内唯一。"""
    __tablename__ = "subproject"
    __table_args__ = (
        UniqueConstraint("main_project_id", "subproject_code", name="uq_subproject_main_project_id_subproject_code"),
        {"schema": SCHEMA},
    )
    main_project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"), nullable=False)
    subproject_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    subproject_type_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ref.subproject_type.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(enum_project, nullable=False, server_default=text("'draft'"))


class Employee(TableBase, AMasterDataMixin):
    """3.4 人员（自然人）。"""
    __tablename__ = "employee"
    __table_args__ = {"schema": SCHEMA}
    emp_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))


class Team(TableBase, AMasterDataMixin):
    """3.4 班组；team_type 含 outsource（SR-6）。"""
    __tablename__ = "team"
    __table_args__ = (
        CheckConstraint("team_type IN ('production','install','outsource','other')", name="ck_team_team_type_values"),
        {"schema": SCHEMA},
    )
    team_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    team_type: Mapped[str] = mapped_column(String(16), nullable=False)


class TeamMembership(TableBase, ALifecycleMixin):
    """3.5 归属历史化；is_current 生成列；主属当前唯一 partial unique。"""
    __tablename__ = "team_membership"
    __table_args__ = (
        Index("ix_team_membership_primary_current", "employee_id", unique=True,
              postgresql_where=text("membership_kind = 'primary' AND is_current")),
        {"schema": SCHEMA},
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    role_in_team: Mapped[str | None] = mapped_column(String(32))
    membership_kind: Mapped[str] = mapped_column(enum_membership, nullable=False)
    joined_at: Mapped[date] = mapped_column(Date, nullable=False)
    left_at: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, Computed("left_at IS NULL", persisted=True))


class SecondmentRecord(TableBase, ALifecycleMixin):
    """3.6 借调；不改变工序归属事实。"""
    __tablename__ = "secondment_record"
    __table_args__ = {"schema": SCHEMA}
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    from_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    to_team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(255))


class TeamLeaderHistory(TableBase, ALifecycleMixin):
    """3.6 组长任职史。"""
    __tablename__ = "team_leader_history"
    __table_args__ = {"schema": SCHEMA}
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    appointed_at: Mapped[date] = mapped_column(Date, nullable=False)
    relieved_at: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class UserAccount(TableBase, AMasterDataMixin):
    """3.7 一人一账号；employee_id 可空（纯系统账号）且唯一（partial WHERE NOT NULL）。"""
    __tablename__ = "user_account"
    __table_args__ = (
        Index("ix_user_account_employee_id_unique", "employee_id", unique=True,
              postgresql_where=text("employee_id IS NOT NULL")),
        {"schema": SCHEMA},
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"))
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Role(TableBase, AMasterDataMixin):
    """3.7 角色（11 初始角色 seed，is_system 标记）。"""
    __tablename__ = "role"
    __table_args__ = {"schema": SCHEMA}
    role_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class Permission(TableBase, AMasterDataMixin):
    """3.7 功能权限 + 五档操作权限。"""
    __tablename__ = "permission"
    __table_args__ = (
        CheckConstraint("perm_kind IN ('functional','op')", name="ck_permission_perm_kind_values"),
        CheckConstraint("op_level IN ('view','execute','modify','review','manage')", name="ck_permission_op_level_values"),
        {"schema": SCHEMA},
    )
    perm_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    perm_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    op_level: Mapped[str] = mapped_column(String(16), nullable=False)


class RolePermission(TableBase):
    """3.7 RBAC 关联。"""
    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission_role_id_permission_id"),
        {"schema": SCHEMA},
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.role.id", ondelete="RESTRICT"), nullable=False)
    permission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.permission.id", ondelete="RESTRICT"), nullable=False)


class UserRole(TableBase):
    """3.7 一人多角色。"""
    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role_user_id_role_id"),
        {"schema": SCHEMA},
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("now()"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.user_account.id", ondelete="RESTRICT"), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.role.id", ondelete="RESTRICT"), nullable=False)


class DataScopePolicy(TableBase, ALifecycleMixin):
    """3.7 五档数据范围；软引用受控 grantee_type∈{role,user}；范围值按 level 取一（服务层）。"""
    __tablename__ = "data_scope_policy"
    __table_args__ = (
        CheckConstraint("scope_level IN ('company','main_project','subproject','team','person')", name="ck_data_scope_policy_scope_level_values"),
        CheckConstraint("grantee_type IN ('role','user')", name="ck_data_scope_policy_grantee_type_values"),
        {"schema": SCHEMA},
    )
    scope_level: Mapped[str] = mapped_column(String(16), nullable=False)
    grantee_type: Mapped[str] = mapped_column(String(8), nullable=False)
    grantee_ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    grantee_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope_main_project_id: Mapped[int | None] = mapped_column(BigInteger)
    scope_subproject_id: Mapped[int | None] = mapped_column(BigInteger)
    scope_team_id: Mapped[int | None] = mapped_column(BigInteger)
    scope_person_id: Mapped[int | None] = mapped_column(BigInteger)


class SegregationRule(TableBase, ALifecycleMixin):
    """3.7 职责分离规则（过磅/检验/结算互斥）。"""
    __tablename__ = "segregation_rule"
    __table_args__ = (
        CheckConstraint("action IN ('warn','block')", name="ck_segregation_rule_action_values"),
        {"schema": SCHEMA},
    )
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    subject_a_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_a_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_b_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_b_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Material(TableBase, ALifecycleMixin):
    """3.8 物料主数据（G-2/N-1 重点）：material_code 全局唯一且不可变（T-7）；
    name+specification 无唯一约束（221 组证据）。"""
    __tablename__ = "material"
    material_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    grade: Mapped[str] = mapped_column(String(64), nullable=False)
    specification: Mapped[str] = mapped_column(String(128), nullable=False)
    thickness_mm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    unit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ref.unit_of_measure.id", ondelete="RESTRICT"), nullable=False)
    weight_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 3))
    management_class: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'raw_material'"))
    supplier_material_code: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (
        CheckConstraint("management_class IN ('raw_material','turnover','fixed_asset','spare_part','consumable','labor_protection')",
                        name="ck_material_management_class_values"),
        Index("ix_material_management_class", "management_class"),
        Index("ix_material_category_specification", "category", "specification"),
        {"schema": SCHEMA},
    )


class Supplier(TableBase, AMasterDataMixin):
    """3.9 供应商。"""
    __tablename__ = "supplier"
    __table_args__ = {"schema": SCHEMA}
    supplier_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(255))


class Warehouse(TableBase, AMasterDataMixin):
    """3.10 仓库。"""
    __tablename__ = "warehouse"
    __table_args__ = (
        CheckConstraint("wh_type IN ('raw','turnover','finished','mixed')", name="ck_warehouse_wh_type_values"),
        {"schema": SCHEMA},
    )
    wh_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    wh_type: Mapped[str] = mapped_column(String(16), nullable=False)


class StorageLocation(TableBase, AMasterDataMixin):
    """3.10 库位；(warehouse_id, loc_code) 唯一。"""
    __tablename__ = "storage_location"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "loc_code", name="uq_storage_location_warehouse_id_loc_code"),
        {"schema": SCHEMA},
    )
    warehouse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.warehouse.id", ondelete="RESTRICT"), nullable=False)
    loc_code: Mapped[str] = mapped_column(String(32), nullable=False)


class TeamOperationCapability(TableBase, ALifecycleMixin):
    """3.4 班组×工序能力（M-N）：仅表达班组可承接的工序范围，绝不作派工/登记强制校验；
    不影响 actual_component 主责/执行班组，劳务归属以实际执行记录为准。"""
    __tablename__ = "team_operation_capability"
    __table_args__ = (
        UniqueConstraint("team_id", "operation_type_id", name="uq_team_operation_capability_team_op"),
        Index("ix_team_operation_capability_operation_type_id", "operation_type_id"),
        {"schema": SCHEMA},
    )
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"), nullable=False)
    operation_type_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ref.operation_type.id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)


class EmployeeOccupation(TableBase, ALifecycleMixin):
    """3.4 员工职业/岗位能力（M-N，多值平权）；md.employee 不加列。
    与 team_operation_capability 正交（职业≠工序能力≠执行班组）。"""
    __tablename__ = "employee_occupation"
    __table_args__ = (
        UniqueConstraint("employee_id", "occupation_id", name="uq_employee_occupation_emp_occ"),
        Index("ix_employee_occupation_occupation_id", "occupation_id"),
        {"schema": SCHEMA},
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("md.employee.id", ondelete="RESTRICT"), nullable=False)
    occupation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("ref.employee_occupation_dict.id", ondelete="RESTRICT"), nullable=False)
