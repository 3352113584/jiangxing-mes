"""Phase 4 生产链纠偏 — G-2 专项测试：production_completed 仅由 E-2 第 17 道 painting（油漆）完成触发。

冻结语义（来自大王业务裁决）：
- production_completed = 构件生产域结束的生命周期枢轴位，仅 painting 完成成立。
- 成品检（step 15）/ 抛丸（step 16）/ 其他工序完成，均不直接触发 production_completed。
- 不再以「所有 production_task 完成 / 所有 route step 完成 / 结算完成 / 发运完成」作为依据。

本文件只读测试，不修改业务代码；覆盖规则 §「必须同时检查」1~9 项：
QR 路径 / task-id 路径 / 重复报工 / 并发报工 / 返工 attempt /
可选工序不误触发 / step15 不触发 / step16 不触发 / step17 触发。

数据库约定见 conftest.py：jiangxing_mes_test @ localhost:15432。
"""
import threading
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_password
from app.db.models.prod_plan import ProductionReport
from app.db.session import SessionLocal
from app.main import app
from app.services.auth_service import UserContext
from app.services.errors import BusinessError
from app.services import registration_service
from helpers import B

NOW = datetime(2026, 9, 19, 9, 0, 0)


def _uid(prefix="x"):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# 测试数据构造助手
# ---------------------------------------------------------------------------
def make_team(conn, code=None):
    code = code or _uid("T")
    return conn.execute(
        "INSERT INTO md.team(team_code, name, team_type) VALUES (%s,%s,'production') RETURNING id",
        (code, code),
    ).fetchone()[0]


def make_project(conn):
    pid = conn.execute(
        "INSERT INTO md.main_project(project_code, name) VALUES (%s,'测试项目') RETURNING id",
        (_uid("P"),),
    ).fetchone()[0]
    sid = conn.execute(
        "INSERT INTO md.subproject(main_project_id, subproject_code, name) VALUES (%s,%s,'测试子项目') RETURNING id",
        (pid, _uid("S")),
    ).fetchone()[0]
    return pid, sid


def make_component(conn, sid, no, qr_code=None):
    qr_code = qr_code or _uid("QR")
    cli = conn.execute(
        "INSERT INTO prod.component_list_item(subproject_id, component_no, name, quantity) "
        "VALUES (%s,%s,'测试构件',1) RETURNING id",
        (sid, no),
    ).fetchone()[0]
    qid = conn.execute(
        "INSERT INTO prod.qr_code_registry(qr_code) VALUES (%s) RETURNING id", (qr_code,)
    ).fetchone()[0]
    acid = conn.execute(
        "INSERT INTO prod.actual_component(subproject_id, component_list_item_id, component_no, "
        "instance_sequence, qr_code_id) VALUES (%s,%s,%s,1,%s) RETURNING id",
        (sid, cli, no, qid),
    ).fetchone()[0]
    conn.execute(
        "UPDATE prod.qr_code_registry SET actual_component_id=%s WHERE id=%s", (acid, qid)
    )
    conn.commit()
    return acid, qr_code


def make_operator(conn, team_id, username=None, password="secret", role="worker"):
    username = username or _uid("u")
    emp_no = f"E{username}"
    emp_id = conn.execute(
        "INSERT INTO md.employee(emp_no, name) VALUES (%s,%s) RETURNING id", (emp_no, username)
    ).fetchone()[0]
    ph = hash_password(password)
    user_id = conn.execute(
        "INSERT INTO md.user_account(username, password_hash, employee_id) VALUES (%s,%s,%s) RETURNING id",
        (username, ph, emp_id),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO md.team_membership(employee_id, team_id, membership_kind, joined_at) "
        "VALUES (%s,%s,'primary', CURRENT_DATE)",
        (emp_id, team_id),
    )
    rid = conn.execute("SELECT id FROM md.role WHERE role_code=%s", (role,)).fetchone()[0]
    conn.execute(
        "INSERT INTO md.user_role(user_id, role_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (user_id, rid),
    )
    conn.commit()
    return {"user_id": user_id, "employee_id": emp_id, "username": username, "password": password}


def make_route_step(conn, pid, step_no, op_code):
    """按 operation_type.code 在指定主项目下创建 route_template_step（同项目复用同一 route_template）。"""
    row = conn.execute("SELECT id FROM eng.route_template WHERE main_project_id=%s LIMIT 1", (pid,)).fetchone()
    if row is None:
        tid = conn.execute(
            "INSERT INTO eng.route_template(main_project_id, name) VALUES (%s,'G2路线') RETURNING id", (pid,)
        ).fetchone()[0]
    else:
        tid = row[0]
    otid = conn.execute("SELECT id FROM ref.operation_type WHERE code=%s", (op_code,)).fetchone()[0]
    return conn.execute(
        "INSERT INTO eng.route_template_step(template_id, step_no, operation_type_id) VALUES (%s,%s,%s) RETURNING id",
        (tid, step_no, otid),
    ).fetchone()[0]


def login(client, username, password="secret"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


def register_via_api(client, token, *, qr_code=None, task_id=None, client_token=None,
                     action_key=None, worker_ids, occurred_at=None):
    body = {
        "qr_code": qr_code,
        "task_id": task_id,
        "client_token": client_token or _uid("tok"),
        "worker_ids": worker_ids,
    }
    if action_key is not None:
        body["action_key"] = action_key
    if occurred_at is not None:
        body["occurred_at"] = occurred_at.isoformat()
    return client.post("/api/android/register", json=body, headers=auth_h(token))


def get_status(conn, acid):
    return conn.execute(
        "SELECT production_status FROM prod.actual_component WHERE id=%s", (acid,)
    ).fetchone()[0]


def assign_and_register(client, token, conn, sid, acid, step_id, team_id, op, qr=None):
    """分配某工序任务并（通过 task-id 路径）登记，返回 task_id。"""
    r = client.post(
        "/api/tasks/assign",
        json={"step_id": step_id, "component_ids": [acid], "team_ids": [team_id]},
        headers=auth_h(token),
    )
    assert r.status_code == 200, r.text
    mt = client.get("/api/android/my-tasks", headers=auth_h(token)).json()
    task_id = next(t["task_id"] for t in mt if t["actual_component_id"] == acid)
    rr = register_via_api(client, token, task_id=task_id, worker_ids=[op["employee_id"]])
    assert rr.status_code == 200, rr.text
    return task_id


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# G-2-L：step 15 成品检完成，不能触发 production_completed
# ---------------------------------------------------------------------------
def test_G2_L_step15_final_inspection_not_completed(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 15, "final_inspection")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C15")
    op = make_operator(conn, t1, "uG2L")
    tok = login(client, op["username"])

    assign_and_register(client, tok, conn, sid, acid, step, t1, op)
    assert get_status(conn, acid) != "production_completed"
    assert get_status(conn, acid) == "in_production"  # 已进入生产但未完成


# ---------------------------------------------------------------------------
# G-2-M：step 16 抛丸完成，不能触发 production_completed
# ---------------------------------------------------------------------------
def test_G2_M_step16_shot_blasting_not_completed(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 16, "shot_blasting")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C16")
    op = make_operator(conn, t1, "uG2M")
    tok = login(client, op["username"])

    assign_and_register(client, tok, conn, sid, acid, step, t1, op)
    assert get_status(conn, acid) != "production_completed"
    assert get_status(conn, acid) == "in_production"


# ---------------------------------------------------------------------------
# G-2-N：step 17 油漆完成，必须正确触发 production_completed
# ---------------------------------------------------------------------------
def test_G2_N_step17_painting_completed(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C17")
    op = make_operator(conn, t1, "uG2N")
    tok = login(client, op["username"])

    assign_and_register(client, tok, conn, sid, acid, step, t1, op)
    assert get_status(conn, acid) == "production_completed"


# ---------------------------------------------------------------------------
# G-2-O：仅 painting 触发 —— 1~16 全部完成仍不触发，直到 painting 完成
# （task-id 路径 + QR 路径都走同一套 register，此处用 task-id 路径）
# ---------------------------------------------------------------------------
def test_G2_O_only_painting_triggers(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    s15 = make_route_step(conn, pid, 15, "final_inspection")
    s16 = make_route_step(conn, pid, 16, "shot_blasting")
    s17 = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, qr = make_component(conn, sid, "C1716")
    op = make_operator(conn, t1, "uG2O")
    tok = login(client, op["username"])

    # step 15
    assign_and_register(client, tok, conn, sid, acid, s15, t1, op)
    assert get_status(conn, acid) == "in_production"
    # step 16
    assign_and_register(client, tok, conn, sid, acid, s16, t1, op)
    assert get_status(conn, acid) == "in_production"  # 1~16 完成，仍未 production_completed
    # step 17（油漆）必须先由 PC 分配任务，再由工人扫码登记（Sprint 1 真实流程）
    r_assign = client.post(
        "/api/tasks/assign",
        json={"step_id": s17, "component_ids": [acid], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    assert r_assign.status_code == 200
    # step 17（油漆）通过 QR 路径登记
    r = register_via_api(client, tok, qr_code=qr, worker_ids=[op["employee_id"]])
    assert r.status_code == 200
    assert get_status(conn, acid) == "production_completed"


# ---------------------------------------------------------------------------
# G-2-P：可选工序（非 E-2 主链，如 outsource_handling）完成，不能误触发
# ---------------------------------------------------------------------------
def test_G2_P_optional_operation_no_trigger(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 99, "outsource_handling")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C99")
    op = make_operator(conn, t1, "uG2P")
    tok = login(client, op["username"])

    assign_and_register(client, tok, conn, sid, acid, step, t1, op)
    assert get_status(conn, acid) != "production_completed"
    assert get_status(conn, acid) == "in_production"


# ---------------------------------------------------------------------------
# G-2-Q：重复报工（同 client_token）幂等，不重复落库，仍 production_completed
# ---------------------------------------------------------------------------
def test_G2_Q_duplicate_painting_idempotent(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C17Q")
    op = make_operator(conn, t1, "uG2Q")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [acid], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    task_id = next(t["task_id"] for t in client.get("/api/android/my-tasks", headers=auth_h(tok)).json()
                   if t["actual_component_id"] == acid)

    token = _uid("tok")
    r1 = register_via_api(client, tok, task_id=task_id, client_token=token, worker_ids=[op["employee_id"]])
    assert r1.status_code == 200 and r1.json()["idempotent"] is False
    r2 = register_via_api(client, tok, task_id=task_id, client_token=token, worker_ids=[op["employee_id"]])
    assert r2.status_code == 200 and r2.json()["idempotent"] is True
    assert r2.json()["report_id"] == r1.json()["report_id"]

    hist = client.get("/api/production-reports", params={"subproject_id": sid}, headers=auth_h(tok)).json()
    assert hist["total"] == 1
    assert get_status(conn, acid) == "production_completed"


# ---------------------------------------------------------------------------
# G-2-R：并发双提交 painting，仅一个有效结果（first-win + ALREADY_COMPLETED）
# ---------------------------------------------------------------------------
def test_G2_R_concurrent_painting(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, _qr = make_component(conn, sid, "C17R")
    task_id = b.task(acid, step, t1)
    conn.commit()
    op = make_operator(conn, t1, "uG2R")
    ctx = UserContext(
        user_id=op["user_id"], username=op["username"], employee_id=op["employee_id"],
        primary_team_id=t1, primary_team_name="t", roles=["worker"],
    )

    results = {}

    def runner(key, token):
        try:
            with SessionLocal() as s:
                res = registration_service.register(
                    s, user_ctx=ctx, task_id=task_id, client_token=token,
                    worker_ids=[op["employee_id"]],
                )
                results[key] = ("ok", res["status"])
        except BusinessError as e:
            results[key] = ("err", e.code)
        except Exception as e:  # noqa: BLE001
            results[key] = ("err_other", type(e).__name__, str(e))

    ta = threading.Thread(target=runner, args=("a", "TOK_A"))
    tb = threading.Thread(target=runner, args=("b", "TOK_B"))
    ta.start(); tb.start(); ta.join(); tb.join()

    oks = [v for v in results.values() if v[0] == "ok"]
    errs = [v for v in results.values() if v[0] == "err"]
    assert len(oks) == 1, results
    assert any(v[1] == "ALREADY_COMPLETED" for v in errs), results

    with SessionLocal() as s:
        cnt = s.execute(
            select(func.count()).select_from(ProductionReport).where(ProductionReport.task_id == task_id)
        ).scalar()
    assert cnt == 1
    assert get_status(conn, acid) == "production_completed"


# ---------------------------------------------------------------------------
# G-2-S：painting 返工（attempt 2）登记，仍正确 production_completed，不重复/不回退
# ---------------------------------------------------------------------------
def test_G2_S_rework_painting_still_completed(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C17S")
    op = make_operator(conn, t1, "uG2S")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [acid], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    mt = client.get("/api/android/my-tasks", headers=auth_h(tok)).json()
    task1 = next(t["task_id"] for t in mt if t["actual_component_id"] == acid)
    # 首次 painting 登记
    r1 = register_via_api(client, tok, task_id=task1, worker_ids=[op["employee_id"]])
    assert r1.status_code == 200
    assert get_status(conn, acid) == "production_completed"

    # 模拟返工：新建 attempt 2 的 painting 任务
    task2 = b.task(acid, step, t1, attempt=2, rework_of=task1)
    conn.commit()
    r2 = register_via_api(client, tok, task_id=task2, client_token=_uid("tok2"),
                          action_key="complete:rework", worker_ids=[op["employee_id"]])
    assert r2.status_code == 200
    assert get_status(conn, acid) == "production_completed"  # 返工后仍完成，未回退/未重复触发异常


# ---------------------------------------------------------------------------
# G-2-T： painting 完成后，早期工序返工不得错误回退 production_completed
# ---------------------------------------------------------------------------
def test_G2_T_early_rework_no_uncomplete(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    s8 = make_route_step(conn, pid, 8, "welding")
    s17 = make_route_step(conn, pid, 17, "painting")
    t1 = make_team(conn)
    acid, _ = make_component(conn, sid, "C8T")
    op = make_operator(conn, t1, "uG2T")
    tok = login(client, op["username"])

    # 先完成 painting（step 17）
    assign_and_register(client, tok, conn, sid, acid, s17, t1, op)
    assert get_status(conn, acid) == "production_completed"

    # 早期工序 welding（step 8）返工（attempt 2）
    task8 = b.task(acid, s8, t1, attempt=2, rework_of=None)
    conn.commit()
    r8 = register_via_api(client, tok, task_id=task8, client_token=_uid("tok8"),
                          action_key="complete:weld-rework", worker_ids=[op["employee_id"]])
    assert r8.status_code == 200
    # 早期工序返工完成，不得把已完成的 production_completed 回退
    assert get_status(conn, acid) == "production_completed"
