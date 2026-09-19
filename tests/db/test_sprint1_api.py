"""Phase 4 Sprint 1 — 验收测试 A~K（真实业务场景）。

覆盖：
- A  多构件批量分配
- B  不同工序 → 不同班组
- C  权限隔离（我的任务只看见本班组）
- D  扫码拒绝非本班组构件（NOT_YOUR_TASK）+ 无效 QR
- E  任务列表选择入口登记
- F/G 同令牌幂等（网络超时重试 / 重复提交）
- H  并发单成功（SELECT ... FOR UPDATE 串行化）
- I  已完成任务重登记状态机（ALREADY_COMPLETED）
- J  PC 生产履历查询
- K  历史事实不可被普通 UPDATE 覆盖（权限矩阵）

数据库约定见 conftest.py：jiangxing_mes_test @ localhost:15432，postgres(管理) / mes_app(应用)。
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
# 测试数据构造助手（基于 raw SQL，沿用 helpers.B）
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


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# A. 多构件批量分配
# ---------------------------------------------------------------------------
def test_A_multi_component_assignment(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    comps = [make_component(conn, sid, f"C{i}")[0] for i in range(3)]
    op = make_operator(conn, t1, "uA")
    tok = login(client, op["username"])

    r = client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": comps, "team_ids": [t1], "split": "equal"},
        headers=auth_h(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 3
    assert all(d["execute_team_id"] == t1 for d in data)
    assert all(d["status"] == "pending" for d in data)

    q = client.get(
        "/api/tasks", params={"subproject_id": sid, "step_id": step}, headers=auth_h(tok)
    )
    assert q.status_code == 200 and len(q.json()) == 3


# ---------------------------------------------------------------------------
# B. 不同工序 → 不同班组
# ---------------------------------------------------------------------------
def test_B_different_ops_different_teams(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step1 = b.route_step(pid, 1)
    step2 = b.route_step(pid, 2)
    t1, t2 = make_team(conn), make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    c2 = make_component(conn, sid, "C2")[0]
    op = make_operator(conn, t1, "uB")
    tok = login(client, op["username"])

    r1 = client.post(
        "/api/tasks/assign",
        json={"step_id": step1, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    r2 = client.post(
        "/api/tasks/assign",
        json={"step_id": step2, "component_ids": [c2], "team_ids": [t2]},
        headers=auth_h(tok),
    )
    assert r1.status_code == 200 and r2.status_code == 200

    q1 = client.get("/api/tasks", params={"step_id": step1}, headers=auth_h(tok)).json()
    q2 = client.get("/api/tasks", params={"step_id": step2}, headers=auth_h(tok)).json()
    assert len(q1) == 1 and q1[0]["execute_team_id"] == t1
    assert len(q2) == 1 and q2[0]["execute_team_id"] == t2
    # 工序隔离：step1 结果不含 step2 构件
    assert q1[0]["actual_component_id"] == c1


# ---------------------------------------------------------------------------
# C. 权限隔离：我的任务只看见本班组被指派构件
# ---------------------------------------------------------------------------
def test_C_my_tasks_isolation(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1, t2 = make_team(conn), make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    op1 = make_operator(conn, t1, "uC1")
    op2 = make_operator(conn, t2, "uC2")
    tok1 = login(client, op1["username"])
    tok2 = login(client, op2["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok1),
    )

    mt1 = client.get("/api/android/my-tasks", headers=auth_h(tok1)).json()
    assert len(mt1) == 1 and mt1[0]["actual_component_id"] == c1
    mt2 = client.get("/api/android/my-tasks", headers=auth_h(tok2)).json()
    assert mt2 == []


# ---------------------------------------------------------------------------
# D. 扫码拒绝非本班组构件 + 无效 QR
# ---------------------------------------------------------------------------
def test_D_scan_not_your_task_and_invalid_qr(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1, t2 = make_team(conn), make_team(conn)
    c1, qr = make_component(conn, sid, "C1")
    op1 = make_operator(conn, t1, "uD1")
    op2 = make_operator(conn, t2, "uD2")
    tok1 = login(client, op1["username"])
    tok2 = login(client, op2["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok1),
    )

    # 非本班组扫码 -> 拒绝
    r = register_via_api(client, tok2, qr_code=qr, worker_ids=[op2["employee_id"]])
    assert r.status_code == 403 and r.json()["code"] == "NOT_YOUR_TASK"

    # 无效 QR -> 404
    r2 = register_via_api(client, tok1, qr_code="QR_NOT_EXIST_999", worker_ids=[op1["employee_id"]])
    assert r2.status_code == 404 and r2.json()["code"] == "COMPONENT_NOT_FOUND"

    # 本班组扫码 -> 成功
    r3 = register_via_api(client, tok1, qr_code=qr, worker_ids=[op1["employee_id"]])
    assert r3.status_code == 200 and r3.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# E. 任务列表选择入口登记
# ---------------------------------------------------------------------------
def test_E_register_via_task_list(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    op = make_operator(conn, t1, "uE")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    mt = client.get("/api/android/my-tasks", headers=auth_h(tok)).json()
    assert len(mt) == 1
    task_id = mt[0]["task_id"]

    r = register_via_api(client, tok, task_id=task_id, worker_ids=[op["employee_id"]])
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["task_id"] == task_id


# ---------------------------------------------------------------------------
# F/G. 同令牌幂等（网络超时重试 / 重复提交）
# ---------------------------------------------------------------------------
def test_FG_idempotent_same_token(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    op = make_operator(conn, t1, "uF")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    task_id = client.get("/api/android/my-tasks", headers=auth_h(tok)).json()[0]["task_id"]

    token = _uid("tok")
    r1 = register_via_api(client, tok, task_id=task_id, client_token=token, worker_ids=[op["employee_id"]])
    assert r1.status_code == 200 and r1.json()["idempotent"] is False
    rid = r1.json()["report_id"]

    # 重试同一令牌（模拟网络超时后的重发）
    r2 = register_via_api(client, tok, task_id=task_id, client_token=token, worker_ids=[op["employee_id"]])
    assert r2.status_code == 200
    assert r2.json()["idempotent"] is True
    assert r2.json()["report_id"] == rid

    # 仅一条报工事实
    hist = client.get("/api/production-reports", params={"subproject_id": sid}, headers=auth_h(tok)).json()
    assert hist["total"] == 1


# ---------------------------------------------------------------------------
# H. 并发单成功（SELECT ... FOR UPDATE 串行化）
# ---------------------------------------------------------------------------
def test_H_concurrent_single_success(conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1, _qr = make_component(conn, sid, "C1")
    task_id = b.task(c1, step, t1)
    conn.commit()
    op = make_operator(conn, t1, "uH")
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


# ---------------------------------------------------------------------------
# I. 已完成任务重登记状态机（ALREADY_COMPLETED）
# ---------------------------------------------------------------------------
def test_I_reregister_completed_state_machine(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    op = make_operator(conn, t1, "uI")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    task_id = client.get("/api/android/my-tasks", headers=auth_h(tok)).json()[0]["task_id"]

    r1 = register_via_api(client, tok, task_id=task_id, worker_ids=[op["employee_id"]])
    assert r1.status_code == 200

    # 换令牌换业务键再次登记 -> 已完成保护
    r2 = register_via_api(
        client, tok, task_id=task_id, action_key="another-action",
        worker_ids=[op["employee_id"]],
    )
    assert r2.status_code == 409 and r2.json()["code"] == "ALREADY_COMPLETED"


# ---------------------------------------------------------------------------
# J. PC 生产履历查询
# ---------------------------------------------------------------------------
def test_J_history_query(client, conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1 = make_component(conn, sid, "C1")[0]
    op = make_operator(conn, t1, "uJ")
    tok = login(client, op["username"])

    client.post(
        "/api/tasks/assign",
        json={"step_id": step, "component_ids": [c1], "team_ids": [t1]},
        headers=auth_h(tok),
    )
    task_id = client.get("/api/android/my-tasks", headers=auth_h(tok)).json()[0]["task_id"]
    register_via_api(client, tok, task_id=task_id, worker_ids=[op["employee_id"]])

    r = client.get("/api/production-reports", params={"subproject_id": sid}, headers=auth_h(tok))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["component_no"] == "C1"
    assert it["execute_team_name"]
    assert op["username"] in it["workers"]
    assert it["channel"] == "manual"
    assert it["task_status"] == "completed"


# ---------------------------------------------------------------------------
# K. 历史事实不可被普通 UPDATE 覆盖（权限矩阵：mes_app 无 production_report UPDATE）
# ---------------------------------------------------------------------------
def test_K_history_not_overridable(conn, app_conn):
    b = B(conn)
    pid, sid = make_project(conn)
    step = b.route_step(pid, 1)
    t1 = make_team(conn)
    c1, _qr = make_component(conn, sid, "C1")
    op = make_operator(conn, t1, "uK")
    task_id = b.task(c1, step, t1)
    conn.commit()
    rid = b.report(task_id, c1, step, t1, action_key="ak1", client_token="ct1")
    conn.commit()

    # 以应用角色 mes_app 尝试直接改写历史事实 -> 必须被权限矩阵拒绝
    with pytest.raises(Exception) as ei:
        app_conn.execute(
            "UPDATE prod.production_report SET channel='manual' WHERE id=%s", (rid,)
        )
    msg = str(ei.value).lower()
    assert "permission denied" in msg or "insufficient privilege" in msg

    # 且历史行仍然存在且未被改写
    row = conn.execute(
        "SELECT channel FROM prod.production_report WHERE id=%s", (rid,)
    ).fetchone()
    assert row is not None and row[0] == "scan"
