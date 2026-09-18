"""G 组导入修正 + I 组构件身份测试（数据库级）。

G（任务书 G）：
- Excel 缺行 ≠ 业务删除：缺失身份在新批次留 invalidated 行（NB-8），原行冻结（T-8），
  清单行仅受控 void（row_status 单向 active→voided），不物理删除；
- 已实例化构件禁止 void（T-12 拒绝）→ 导入修正侧转 conflict 留人工决策；
- 修正审批留痕：import_correction_result（rows_invalidated 计数）。

I（任务书 I）：
- 构件唯一身份三元组 (subproject_id, component_no, instance_sequence)；
- QR 全局唯一 + 码-件 1:1（双向唯一）；
- sequence 不复用（身份三元组拒绝回收复用）；
- 报废后补件=新建身份（replacement_for 指向态必须 scrapped，T-2；一补一，partial unique）。
"""
import psycopg
import pytest

from conftest import fails
from helpers import B, NOW


def _make_batch(conn, sid, user, file_hash, import_kind, supersedes=None):
    return conn.execute(
        "INSERT INTO imp.component_list_import_batch(subproject_id, source_file_name, file_hash, "
        "mapping_version, batch_status, import_kind, supersedes_batch_id, imported_by, imported_at, "
        "occurred_at) VALUES (%s, %s, %s, 1, 'approved', %s, %s, %s, %s, %s) RETURNING id",
        (sid, f"{file_hash}.xlsx", file_hash, import_kind, supersedes, user, NOW, NOW)).fetchone()[0]


def _make_row(conn, batch_id, row_no, identity, status, cli_id=None, corrected_from=None):
    return conn.execute(
        "INSERT INTO imp.import_row(import_batch_id, source_row_number, source_identity, raw_payload, "
        "result_status, target_ref_type, target_ref_id, corrected_from_row_id, occurred_at) "
        "VALUES (%s, %s, %s, '{}', %s, %s, %s, %s, %s) RETURNING id",
        (batch_id, row_no, identity, status,
         "component_list_item" if cli_id else None, cli_id, corrected_from, NOW)).fetchone()[0]


# ============ G-1 缺行 ≠ 删除：invalidated 受控失效 ============

def test_g1_missing_row_invalidated_not_deleted(conn):
    b = B(conn)
    user = b.user()
    _, sid = b.project()

    # 初始导入：3 行 created，各回链一条清单行
    b1 = _make_batch(conn, sid, user, "hash-g1", "initial")
    items, rows = [], []
    for i in (1, 2, 3):
        cli = b.list_item(sid, no=f"G{i}")
        r = _make_row(conn, b1, i, f"G{i}", "created", cli_id=cli)
        conn.execute("UPDATE prod.component_list_item SET import_row_id=%s WHERE id=%s", (r, cli))
        items.append(cli)
        rows.append(r)

    # 修正版：G1 kept / G2 updated / G3 缺失 → invalidated 留证
    b2 = _make_batch(conn, sid, user, "hash-g2", "corrected_resubmit", supersedes=b1)
    _make_row(conn, b2, 1, "G1", "kept", cli_id=items[0], corrected_from=rows[0])
    _make_row(conn, b2, 2, "G2", "updated", cli_id=items[1], corrected_from=rows[1])
    _make_row(conn, b2, 3, "G3", "invalidated", corrected_from=rows[2])

    # 修正审批留痕（NB-8 rows_invalidated）
    conn.execute(
        "INSERT INTO imp.import_correction_result(new_batch_id, rows_created, rows_updated, rows_kept, "
        "rows_conflict, rows_rejected, rows_invalidated, decided_by, decided_at, occurred_at) "
        "VALUES (%s, 0, 1, 1, 0, 0, 1, %s, %s, %s)", (b2, user, NOW, NOW))

    # 审批通过后：未实例化的 G3 受控 void（非物理删除）；G1/G2 保持 active
    conn.execute("UPDATE prod.component_list_item SET row_status='voided' WHERE id=%s", (items[2],))

    # —— 断言 ——
    n_items = conn.execute("SELECT count(*) FROM prod.component_list_item WHERE subproject_id=%s",
                           (sid,)).fetchone()[0]
    assert n_items == 3, "Excel 缺行不等于物理删除：3 条清单行全部留存"
    st = [conn.execute("SELECT row_status FROM prod.component_list_item WHERE id=%s", (i,)).fetchone()[0]
          for i in items]
    assert st == ["active", "active", "voided"], "仅未实例化缺失行走受控 void"
    old = conn.execute("SELECT result_status FROM imp.import_row WHERE id=%s", (rows[2],)).fetchone()[0]
    assert old == "created", "原批次行冻结不改（T-8），失效证据在新批次留 invalidated 行"
    inv = conn.execute("SELECT count(*) FROM imp.import_row WHERE import_batch_id=%s AND result_status='invalidated'",
                       (b2,)).fetchone()[0]
    assert inv == 1
    n_inv = conn.execute("SELECT rows_invalidated FROM imp.import_correction_result WHERE new_batch_id=%s",
                         (b2,)).fetchone()[0]
    assert n_inv == 1
    # 原行禁止物理删除（两批次原文留存）
    fails(conn, psycopg.errors.RaiseException,
          "DELETE FROM imp.import_row WHERE id=%s", (rows[0],), frag="T-8")


# ============ G-2 已实例化构件禁止 void → 转 conflict ============

def test_g2_instantiated_item_conflict_not_void(conn):
    b = B(conn)
    user = b.user()
    _, sid = b.project()

    b1 = _make_batch(conn, sid, user, "hash-g2b", "initial")
    cli = b.list_item(sid, no="G10")
    row1 = _make_row(conn, b1, 1, "G10", "created", cli_id=cli)
    b.component(sid, cli, "G10")  # 已实例化

    b2 = _make_batch(conn, sid, user, "hash-g2c", "corrected_resubmit", supersedes=b1)

    # 修正版试图 void 已实例化清单行：DB 层 T-12 拒绝
    fails(conn, psycopg.errors.RaiseException,
          "UPDATE prod.component_list_item SET row_status='voided' WHERE id=%s", (cli,),
          frag="已实例化构件，禁止 void")

    # 应用层将修正行转 conflict 留人工决策（不偷偷改状态）
    _make_row(conn, b2, 1, "G10", "conflict", cli_id=cli, corrected_from=row1)
    st = conn.execute("SELECT row_status FROM prod.component_list_item WHERE id=%s", (cli,)).fetchone()[0]
    assert st == "active", "冲突清单行保持 active，等待人工决策"
    n_conf = conn.execute("SELECT count(*) FROM imp.import_row WHERE import_batch_id=%s AND result_status='conflict'",
                          (b2,)).fetchone()[0]
    assert n_conf == 1


# ============ I-1 构件唯一身份三元组 ============

def test_i1_component_identity_triple_unique(conn):
    b = B(conn)
    _, sid = b.project()
    cli = b.list_item(sid)
    b.component(sid, cli, "I1", seq=1)
    # 同清单行第二件：seq=2 合法（清单行 quantity 语义）
    b.component(sid, cli, "I1", seq=2)
    # 身份三元组重复（sequence 回收复用）被拒
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.actual_component(subproject_id, component_list_item_id, component_no, "
          "instance_sequence, qr_code_id) VALUES (%s, %s, 'I1', 1, %s)",
          (sid, cli, b.qr()), frag="uq_actual_component_identity_triple")


# ============ I-2 QR 唯一 + 码-件 1:1 ============

def test_i2_qr_unique_and_one_to_one(conn):
    b = B(conn)
    _, sid = b.project()
    cli = b.list_item(sid)

    # 码本身全局唯一
    conn.execute("INSERT INTO prod.qr_code_registry(qr_code) VALUES ('QR-DUP')")
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.qr_code_registry(qr_code) VALUES ('QR-DUP')",
          frag="uq_qr_code_registry_qr_code")

    # 码 → 件方向：一码绑两件被拒
    q1 = b.qr("QR-A1")
    ac1 = b.component(sid, cli, "I2", seq=1, qr_id=q1)
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.actual_component(subproject_id, component_list_item_id, component_no, "
          "instance_sequence, qr_code_id) VALUES (%s, %s, 'I2', 2, %s)",
          (sid, cli, q1), frag="ix_actual_component_qr_code_id")

    # 件 → 码方向：一件挂两码被拒
    q2 = b.qr("QR-A2")
    fails(conn, psycopg.errors.UniqueViolation,
          "UPDATE prod.qr_code_registry SET actual_component_id=%s WHERE id=%s",
          (ac1, q2), frag="ix_qr_code_registry_actual_component_unique")
    _ = ac1


# ============ I-3 sequence 不复用 + 报废补件新建身份 ============

def test_i3_sequence_not_reused_replacement_new_identity(conn):
    b = B(conn)
    _, sid = b.project()
    cli = b.list_item(sid)

    ac1 = b.component(sid, cli, "I3", seq=1)
    # 报废事实 + 指向态置 scrapped
    exc = conn.execute("SELECT id FROM ref.exception_category ORDER BY id LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO prod.component_scrap_record(actual_component_id, scrap_no, reason_category_id, "
                 "occurred_at) VALUES (%s, 'SCRAP-I3', %s, %s)", (ac1, exc, NOW))
    conn.execute("UPDATE prod.actual_component SET production_status='scrapped' WHERE id=%s", (ac1,))

    # 补件=新建身份：seq=2（不复用 seq=1），replacement_for 指向报废件
    ac2 = b.component(sid, cli, "I3", seq=2, qr_id=None)
    conn.execute("UPDATE prod.actual_component SET replacement_for=%s WHERE id=%s", (ac1, ac2))

    # sequence 复用被拒：新件不能占用已报废件的 seq=1
    fails(conn, psycopg.errors.UniqueViolation,
          "INSERT INTO prod.actual_component(subproject_id, component_list_item_id, component_no, "
          "instance_sequence, qr_code_id) VALUES (%s, %s, 'I3', 1, %s)",
          (sid, cli, b.qr()), frag="uq_actual_component_identity_triple")

    # 一补一：第二个补件指向同一报废件被拒（partial unique）
    ac3 = b.component(sid, cli, "I3", seq=3)
    fails(conn, psycopg.errors.UniqueViolation,
          "UPDATE prod.actual_component SET replacement_for=%s WHERE id=%s", (ac1, ac3),
          frag="ix_actual_component_replacement_for_unique")

    # 指向未报废构件被拒（T-2：指向态必须 scrapped）
    ac4 = b.component(sid, cli, "I3", seq=4)
    fails(conn, psycopg.errors.RaiseException,
          "UPDATE prod.actual_component SET replacement_for=%s WHERE id=%s", (ac4, ac3), frag="T-2")
