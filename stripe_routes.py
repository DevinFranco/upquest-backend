"""
UpQuest â Stripe payment routes
Handles Checkout sessions, webhooks, and subscription management.
"""

import os
import json
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from fastapi.responses import JSONResponse

from supabase_client import get_supabase_client

router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

PRICE_MONTHLY   = os.environ.get("STRIPE_PRICE_MONTHLY", "price_monthly_placeholder")
PRICE_YEARLY    = os.environ.get("STRIPE_PRICE_YEARLY",  "price_yearly_placeholder")
PRICE_LIFETIME  = os.environ.get("STRIPE_PRICE_LIFETIME","price_lifetime_placeholder")


@router.post("/create-checkout")
async def create_checkout(request: Request):
    body = await request.json()
    plan    = body.get("plan", "monthly")
    user_id = body.get("user_id")
    email   = body.get("email", "")
    price_map = {"monthly": PRICE_MONTHLY, "yearly": PRICE_YEARLY, "lifetime": PRICE_LIFETIME}
    price_id = price_map.get(plan, PRICE_MONTHLY)
    mode = "payment" if plan == "lifetime" else "subscription"
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"], mode=mode,
            customer_email=email or None,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=os.environ.get("STRIPE_SUCCESS_URL", "upquest://payment-success?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=os.environ.get("STRIPE_CANCEL_URL", "upquest://payment-cancel"),
            metadata={"user_id": user_id, "plan": plan},
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    supabase = get_supabase_client()
    data = event["data"]["object"]
    if event["type"] in ("customer.subscription.created", "customer.subscription.updated"):
        user_id = data.get("metadata", {}).get("user_id")
        if user_id:
            period_end = datetime.utcfromtimestamp(data["current_period_end"])
            supabase.table("subscriptions").upsert({"user_id": user_id, "stripe_sub_id": data["id"], "status": data["status"], "plan": data["items"]["data"][0]["price"]["id"], "period_end": period_end.isoformat(), "updated_at": datetime.utcnow().isoformat()}).execute()
    elif event["type"] == "customer.subscription.deleted":
        supabase.table("subscriptions").update({"status": "cancelled", "updated_at": datetime.utcnow().isoformat()}).eq("stripe_sub_id", data["id"]).execute()
    elif event["type"] == "checkout.session.completed":
        meta = data.get("metadata", {})
        user_id = meta.get("user_id")
        if user_id and meta.get("plan") == "lifetime":
            supabase.table("subscriptions").upsert({"user_id": user_id, "stripe_sub_id": data["id"], "status": "active", "plan": "lifetime", "period_end": "2099-12-31T00:00:00", "updated_at": datetime.utcnow().isoformat()}).execute()
    return {"received": True}


@router.post("/portal")
async def customer_portal(request: Request):
    body = await request.json()
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required.")
    supabase = get_supabase_client()
    result = supabase.table("subscriptions").select("stripe_sub_id").eq("user_id", user_id).maybe_single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="No subscription found.")
    sub = stripe.Subscription.retrieve(result.data["stripe_sub_id"])
    session = stripe.billing_portal.Session.create(customer=sub["customer"], return_url=os.environ.get("STRIPE_PORTAL_RETURN_URL", "upquest://profile"))
    return {"portal_url": session.url}
