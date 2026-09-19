"""Phase 4 Sprint 1 — 构件相关辅助（QR 解析、构件实例化）。

构件实例化（list_item.quantity → N 行 actual_component，每件一 QR）是任务分配的前提数据准备，
复用既有 actual_component / qr_code_registry 表，不新增实体/字段。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.prod_component import ActualComponent, ComponentListItem, QrCodeRegistry


def resolve_component_by_qr(db: Session, qr_code: str) -> Optional[ActualComponent]:
    qr = db.execute(
        select(QrCodeRegistry).where(QrCodeRegistry.qr_code == qr_code)
    ).scalar_one_or_none()
    if qr is None or qr.actual_component_id is None:
        return None
    return db.get(ActualComponent, qr.actual_component_id)


def instantiate_list_item(
    db: Session, list_item_id: int, qr_prefix: str = "QR"
) -> list[ActualComponent]:
    """将构件清单行按 quantity 展开为 actual_component（已实例化则补齐差额）。"""
    cli = db.get(ComponentListItem, list_item_id)
    if cli is None:
        return []
    existing = db.execute(
        select(func.count())
        .select_from(ActualComponent)
        .where(ActualComponent.component_list_item_id == list_item_id)
    ).scalar() or 0
    if existing >= cli.quantity:
        return list(
            db.execute(
                select(ActualComponent).where(
                    ActualComponent.component_list_item_id == list_item_id
                )
            ).scalars().all()
        )
    created: list[ActualComponent] = []
    for seq in range(existing + 1, cli.quantity + 1):
        qr = QrCodeRegistry(qr_code=f"{qr_prefix}-{cli.component_no}-{seq}")
        db.add(qr)
        db.flush()
        ac = ActualComponent(
            subproject_id=cli.subproject_id,
            component_list_item_id=cli.id,
            component_no=cli.component_no,
            instance_sequence=seq,
            qr_code_id=qr.id,
        )
        db.add(ac)
        db.flush()
        qr.actual_component_id = ac.id
        created.append(ac)
    db.commit()
    return created
