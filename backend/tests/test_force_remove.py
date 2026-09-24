from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.models import HangRail, RailPlacement, Store, WorkOrder


def _make_order(db, *, status, due, ticket="HR-9001", hung=True):
    store = Store(name=f"测试门店-{ticket}")
    db.add(store)
    db.flush()
    rail = HangRail(store_id=store.id, label="T 杆", length_cm=200)
    db.add(rail)
    order = WorkOrder(
        store_id=store.id,
        ticket_code=ticket,
        garment_name="测试大衣",
        length_cm=40,
        status=status,
        due_at=due,
        hung_at=datetime.utcnow() if hung else None,
    )
    db.add(order)
    db.flush()
    placement = None
    if hung:
        placement = RailPlacement(rail_id=rail.id, order_id=order.id, start_cm=10, end_cm=50)
        db.add(placement)
    db.commit()
    return order, rail, placement


def test_force_remove_releases_active_and_sets_overdue(client, db_session):
    order, rail, placement = _make_order(db_session, status="hung", due=datetime.utcnow() - timedelta(hours=1))

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})

    assert res.status_code == 200
    data = res.json()
    assert data["order"]["status"] == "overdue"
    # active 占位被释放
    db_session.expire_all()
    assert db_session.get(RailPlacement, placement.id).active == 0
    assert db_session.get(WorkOrder, order.id).status == "overdue"


def test_force_remove_response_contains_rail_and_range(client, db_session):
    order, rail, placement = _make_order(db_session, status="hung", due=datetime.utcnow() - timedelta(hours=1))

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})

    assert res.status_code == 200
    released = res.json()["released"]
    assert len(released) == 1
    seg = released[0]
    assert seg["rail_id"] == rail.id
    assert seg["rail_label"] == "T 杆"
    assert seg["start_cm"] == 10
    assert seg["end_cm"] == 50


def test_force_remove_rejects_unexpired_hung(client, db_session):
    order, rail, placement = _make_order(db_session, status="hung", due=datetime.utcnow() + timedelta(days=1))

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})

    assert res.status_code == 400
    db_session.expire_all()
    # 未到期单不得被动：仍占杆、状态不变
    assert db_session.get(RailPlacement, placement.id).active == 1
    assert db_session.get(WorkOrder, order.id).status == "hung"


def test_force_remove_allows_overdue_still_occupying(client, db_session):
    order, rail, placement = _make_order(db_session, status="overdue", due=datetime.utcnow() - timedelta(days=1))

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})

    assert res.status_code == 200
    assert res.json()["order"]["status"] == "overdue"
    db_session.expire_all()
    assert db_session.get(RailPlacement, placement.id).active == 0


def test_force_remove_without_placement_rejected(client, db_session):
    order, _rail, _ = _make_order(
        db_session, status="overdue", due=datetime.utcnow() - timedelta(days=1), ticket="HR-9002", hung=False
    )

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})

    assert res.status_code == 400


def test_force_remove_clears_occupancy_segment(client, db_session):
    order, rail, _ = _make_order(db_session, status="hung", due=datetime.utcnow() - timedelta(hours=2))

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})
    assert res.status_code == 200

    occ = client.get(f"/api/occupancy/{rail.id}").json()
    assert occ["segments"] == []


def test_force_remove_distinct_from_pickup(client, db_session):
    """普通取件走票号且只认 hung；强制出杆后工单为 overdue，取件入口不能再操作它。"""
    order, rail, placement = _make_order(
        db_session, status="hung", due=datetime.utcnow() - timedelta(hours=1), ticket="HR-FORCE-1"
    )

    res = client.post("/api/overdue/force-remove", json={"order_id": order.id})
    assert res.status_code == 200

    # 取件码核验入口对已强制出杆的工单拒绝
    pickup = client.post("/api/pickup", json={"ticket_code": "HR-FORCE-1"})
    assert pickup.status_code == 400

    # 普通取件入口对在杆 hung 单仍正常工作
    other, _r, p2 = _make_order(
        db_session, status="hung", due=datetime.utcnow() + timedelta(days=1), ticket="HR-NORMAL-1"
    )
    ok = client.post("/api/pickup", json={"ticket_code": "HR-NORMAL-1"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "picked"
    db_session.expire_all()
    assert db_session.get(RailPlacement, p2.id).active == 0


def test_overdue_list_flags_occupying(client, db_session):
    occupying, _r1, _ = _make_order(
        db_session, status="overdue", due=datetime.utcnow() - timedelta(hours=3), ticket="HR-OCC-1", hung=True
    )
    bare, _r2, _ = _make_order(
        db_session, status="overdue", due=datetime.utcnow() - timedelta(hours=3), ticket="HR-OCC-2", hung=False
    )

    rows = client.get("/api/overdue").json()
    flags = {r["id"]: r["occupying"] for r in rows}
    assert flags[occupying.id] is True
    assert flags[bare.id] is False
