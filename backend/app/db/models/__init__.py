"""Import all ORM model modules so Base.metadata registers all 131 tables.

Table count per schema (design doc chapter 1):
ref=13, md=18, eng=11, imp=5, prod=34, whs=23, ship=14, aud=13 → 131.
"""
from app.db.models import aud, eng, imp, md, prod_component, prod_plan, prod_quality, ref, ship, whs_procurement, whs_stock  # noqa: F401

__all__ = [
    "ref", "md", "eng", "imp", "prod_component", "prod_plan",
    "prod_quality", "whs_procurement", "whs_stock", "ship", "aud",
]
