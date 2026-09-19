"""eng schema — Layer 3 engineering definitions: drawings / BOM / route templates (11 tables).

Design doc: database_design_v1.2.md chapter 4.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ALifecycleMixin, AMasterDataMixin, Base, BFactMixin, TableBase
from app.db.enums import enum_line_status, enum_step_status

SCHEMA = "eng"


class EngineeringObject(TableBase, AMasterDataMixin):  # A-class per 18.3
    """4.1 外部工程对象（与软件无关）。"""
    __tablename__ = "engineering_object"
    __table_args__ = (
        UniqueConstraint("source_system", "ext_object_key", name="uq_engineering_object_source_system_ext_object_key"),
        {"schema": SCHEMA},
    )
    source_system: Mapped[str] = mapped_column(String(32), nullable=False)
    ext_object_key: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(
        String(32),
        CheckConstraint("object_type IN ('structure','part','assembly','other')", name="ck_engineering_object_object_type_values"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class Drawing(TableBase, ALifecycleMixin):
    """4.1 图纸。"""
    __tablename__ = "drawing"
    __table_args__ = {"schema": SCHEMA}
    drawing_no: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64))
    engineering_object_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("eng.engineering_object.id", ondelete="RESTRICT"))


class DrawingRevision(TableBase, BFactMixin):
    """4.1 图纸版次（B 类）；(drawing_id, revision_no) 唯一；历史版本只追加不删。"""
    __tablename__ = "drawing_revision"
    __table_args__ = (
        UniqueConstraint("drawing_id", "revision_no", name="uq_drawing_revision_drawing_id_revision_no"),
        {"schema": SCHEMA},
    )
    drawing_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.drawing.id", ondelete="RESTRICT"), nullable=False)
    revision_no: Mapped[str] = mapped_column(String(32), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    file_ref: Mapped[str | None] = mapped_column(String(512))
    is_effective: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class EngineeringBinding(TableBase, ALifecycleMixin):
    """4.1 工程绑定（关系 58/60/61）：清单行继承+单件例外；目标软引用受控二值。"""
    __tablename__ = "engineering_binding"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", "engineering_object_id", name="uq_engineering_binding_target_object"),
        CheckConstraint("target_type IN ('component_list_item','actual_component')", name="ck_engineering_binding_target_type_values"),
        Index("ix_engineering_binding_target", "target_type", "target_id"),
        {"schema": SCHEMA},
    )
    engineering_object_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.engineering_object.id", ondelete="RESTRICT"), nullable=False)
    drawing_revision_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.drawing_revision.id", ondelete="RESTRICT"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EngineeringChange(TableBase, BFactMixin):
    """4.1 工程变更（旧版→新版）。"""
    __tablename__ = "engineering_change"
    __table_args__ = {"schema": SCHEMA}
    change_no: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    old_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("eng.drawing_revision.id", ondelete="RESTRICT"))
    new_revision_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.drawing_revision.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(512))
    initiated_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account


class EngineeringChangeItem(TableBase, BFactMixin):
    """4.1 变更受影响对象行；目标软引用（构件/零件）。"""
    __tablename__ = "engineering_change_item"
    __table_args__ = (
        UniqueConstraint("change_id", "target_type", "target_id", name="uq_engineering_change_item_target"),
        CheckConstraint("target_type IN ('actual_component','part_instance')", name="ck_engineering_change_item_target_type_values"),
        Index("ix_engineering_change_item_target", "target_type", "target_id"),
        {"schema": SCHEMA},
    )
    change_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.engineering_change.id", ondelete="RESTRICT"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    production_status_snapshot: Mapped[str | None] = mapped_column(String(32))


class ChangeDisposition(TableBase, BFactMixin):
    """4.1 技术处置意见（1—1 变更行）；rework_order_id 可空触发。"""
    __tablename__ = "change_disposition"
    __table_args__ = (
        UniqueConstraint("change_item_id", name="uq_change_disposition_change_item_id"),
        CheckConstraint("disposition IN ('continue_use','rework','scrap')", name="ck_change_disposition_disposition_values"),
        {"schema": SCHEMA},
    )
    change_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.engineering_change_item.id", ondelete="RESTRICT"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    rework_order_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("prod.rework_order.id", ondelete="RESTRICT"))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)  # → md.user_account
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class ComponentBomTemplate(TableBase, ALifecycleMixin):
    """4.2 BOM 模板头；当前生效版次 partial unique。"""
    __tablename__ = "component_bom_template"
    __table_args__ = (
        Index("ix_component_bom_template_effective", "component_list_item_id", unique=True,
              postgresql_where=text("is_effective")),
        UniqueConstraint("component_list_item_id", "drawing_revision_id", name="uq_component_bom_template_list_item_revision"),
        {"schema": SCHEMA},
    )
    component_list_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("prod.component_list_item.id", ondelete="RESTRICT"), nullable=False)
    drawing_revision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("eng.drawing_revision.id", ondelete="RESTRICT"))
    template_no: Mapped[str | None] = mapped_column(String(32))
    is_effective: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class BomTemplateLine(TableBase, ALifecycleMixin):
    """4.3 BOM 模板行（MCR-1 不可变重点）；新内容=新行新 line_no；语义列被引用后 T-4 禁改。"""
    __tablename__ = "bom_template_line"
    __table_args__ = (
        UniqueConstraint("template_id", "line_no", name="uq_bom_template_line_template_id_line_no"),
        CheckConstraint("qty_per_component > 0", name="ck_bom_template_line_qty_per_component_positive"),
        {"schema": SCHEMA},
    )
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.component_bom_template.id", ondelete="RESTRICT"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    part_no: Mapped[str] = mapped_column(String(64), nullable=False)
    part_name: Mapped[str | None] = mapped_column(String(128))
    material_desc: Mapped[str | None] = mapped_column(String(128))
    qty_per_component: Mapped[int] = mapped_column(Integer, nullable=False)
    process_attr: Mapped[str | None] = mapped_column(String(64))
    line_status: Mapped[str] = mapped_column(enum_line_status, nullable=False, server_default=text("'active'"))


class RouteTemplate(TableBase, ALifecycleMixin):
    """4.4 路线模板（N-6 双归属：主/子项目至少一非空）。"""
    __tablename__ = "route_template"
    __table_args__ = (
        CheckConstraint("main_project_id IS NOT NULL OR subproject_id IS NOT NULL", name="ck_route_template_scope_at_least_one"),
        {"schema": SCHEMA},
    )
    main_project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"))
    subproject_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class RouteTemplateStep(TableBase, ALifecycleMixin):
    """4.4 工序行（MCR-1 同构）；被引用后语义列 T-5 禁改。

    M-P4-3：operation_type_id 改为可空，新增 project_operation_id，二者互斥
    （标准工序=operation_type_id，项目自定义工序=project_operation_id）。"""
    __tablename__ = "route_template_step"
    __table_args__ = (
        UniqueConstraint("template_id", "step_no", name="uq_route_template_step_template_id_step_no"),
        CheckConstraint(
            "(operation_type_id IS NOT NULL AND project_operation_id IS NULL) OR "
            "(operation_type_id IS NULL AND project_operation_id IS NOT NULL)",
            name="ck_rts_op_xor"),
        {"schema": SCHEMA},
    )
    template_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("eng.route_template.id", ondelete="RESTRICT"), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ref.operation_type.id", ondelete="RESTRICT"), nullable=True)
    project_operation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("eng.project_operation.id", ondelete="RESTRICT"), nullable=True)
    default_requirement: Mapped[str | None] = mapped_column(String(255))
    step_status: Mapped[str] = mapped_column(enum_step_status, nullable=False, server_default=text("'active'"))


# ============ M-P4-3 生产成本 / 班组结算口径模型 ============
# 项目工序身份（A 类主数据）与工序价格版本（B 类历史事实）。
# default_team_id 仅用于未来任务生成默认班组，绝不参与实际成本归属。

class ProjectOperation(TableBase, AMasterDataMixin):
    """M-P4-3 项目工序稳定身份：标准工序(operation_type_id) 与 自定义工序(custom_name) 互斥。"""
    __tablename__ = "project_operation"
    __table_args__ = (
        CheckConstraint(
            "(operation_type_id IS NOT NULL AND custom_name IS NULL) OR "
            "(operation_type_id IS NULL AND custom_name IS NOT NULL)",
            name="ck_po_identity"),
        CheckConstraint("main_project_id IS NOT NULL OR subproject_id IS NOT NULL", name="ck_po_scope"),
        UniqueConstraint("main_project_id", "project_operation_code", name="uq_po_main_project_code"),
        UniqueConstraint("subproject_id", "project_operation_code", name="uq_po_subproject_code"),
        {"schema": SCHEMA},
    )
    main_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.main_project.id", ondelete="RESTRICT"))
    subproject_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.subproject.id", ondelete="RESTRICT"))
    project_operation_code: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_type_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ref.operation_type.id", ondelete="RESTRICT"))
    custom_name: Mapped[str | None] = mapped_column(String(128))
    default_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("md.team.id", ondelete="RESTRICT"))


class ProjectOperationPrice(TableBase, BFactMixin):
    """M-P4-3 不可破坏的历史价格版本（B 类事实）。T-17 守卫：区间不重叠、单一当前、已生效冻结。"""
    __tablename__ = "project_operation_price"
    __table_args__ = (
        UniqueConstraint("project_operation_id", "version_no", name="uq_pop_po_version"),
        CheckConstraint(
            "price_basis IN ('weight','piece','length','hour','hole_count')",
            name="ck_pop_price_basis"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_pop_range"),
        Index("ix_pop_lookup", "project_operation_id", "effective_from", "effective_to"),
        Index("uq_pop_current", "project_operation_id", unique=True,
              postgresql_where=text("is_current")),
        {"schema": SCHEMA},
    )
    project_operation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eng.project_operation.id", ondelete="RESTRICT"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    price_basis: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
