from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, status

from app.core.errors import ValidationFailed
from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.pricing import service
from app.modules.pricing.schemas import (
    BulkRatesIn,
    BulkResultOut,
    GridOut,
    OfferOut,
    PolicyIn,
    PolicyOut,
    PolicyUpdate,
    PricingRuleIn,
    PricingRuleOut,
    PricingRuleUpdate,
    RatePlanIn,
    RatePlanOut,
    RatePlanUpdate,
)

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["pricing"])

View = hotel_ctx(P.PRICING_VIEW)
Manage = hotel_ctx(P.PRICING_MANAGE)
Sell = hotel_ctx(P.RESERVATIONS_VIEW)


@router.get("/rate-plans", response_model=list[RatePlanOut])
async def list_plans(ctx: Sell, db: DB):
    return await service.list_plans(db, ctx.hotel_id)


@router.post("/rate-plans", response_model=RatePlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(body: RatePlanIn, ctx: Manage, db: DB):
    return await service.create_plan(db, ctx, body)


@router.patch("/rate-plans/{plan_id}", response_model=RatePlanOut)
async def update_plan(plan_id: uuid.UUID, body: RatePlanUpdate, ctx: Manage, db: DB):
    return await service.update_plan(db, ctx, plan_id, body)


@router.delete("/rate-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(plan_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_plan(db, ctx, plan_id)


@router.get("/pricing-rules", response_model=list[PricingRuleOut])
async def list_rules(ctx: View, db: DB):
    return await service.list_rules(db, ctx.hotel_id)


@router.post("/pricing-rules", response_model=PricingRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(body: PricingRuleIn, ctx: Manage, db: DB):
    return await service.create_rule(db, ctx, body)


@router.patch("/pricing-rules/{rule_id}", response_model=PricingRuleOut)
async def update_rule(rule_id: uuid.UUID, body: PricingRuleUpdate, ctx: Manage, db: DB):
    return await service.update_rule(db, ctx, rule_id, body)


@router.delete("/pricing-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_rule(db, ctx, rule_id)


@router.get("/cancellation-policies", response_model=list[PolicyOut])
async def list_policies(ctx: Sell, db: DB):
    return await service.list_policies(db, ctx.hotel_id)


@router.post("/cancellation-policies", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(body: PolicyIn, ctx: Manage, db: DB):
    return await service.create_policy(db, ctx, body)


@router.patch("/cancellation-policies/{policy_id}", response_model=PolicyOut)
async def update_policy(policy_id: uuid.UUID, body: PolicyUpdate, ctx: Manage, db: DB):
    return await service.update_policy(db, ctx, policy_id, body)


@router.delete("/cancellation-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(policy_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_policy(db, ctx, policy_id)


@router.get("/rates/grid", response_model=GridOut)
async def grid(ctx: View, db: DB, rate_plan_id: uuid.UUID, start: date, end: date):
    return await service.grid(db, ctx.hotel_id, rate_plan_id, start, end)


@router.post("/rates/bulk", response_model=BulkResultOut)
async def bulk(body: BulkRatesIn, ctx: Manage, db: DB):
    return BulkResultOut(cells_changed=await service.bulk_update(db, ctx, body))


@router.get("/rates/offers", response_model=list[OfferOut])
async def offers(
    ctx: Sell,
    db: DB,
    arrival: date,
    departure: date,
    adults: int = Query(2, ge=1, le=50),
    children: int = Query(0, ge=0, le=50),
    room_type_id: uuid.UUID | None = None,
):
    if departure <= arrival or (departure - arrival).days > 365:
        raise ValidationFailed("INVALID_RANGE")
    return await service.offers(db, ctx.hotel_id, arrival, departure, adults, children, room_type_id)
