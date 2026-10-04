"""FastAPI application for the local member-management demo."""

import asyncio

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Demo Member Management")
app.mount("/static", StaticFiles(directory="demo_app/static"), name="static")
templates = Jinja2Templates(directory="demo_app/templates")


MEMBERS = {
    "12345": {"name": "John Smith", "savings": "$5430.25", "checking": "$1200.00"},
    "67890": {"name": "Jane Doe", "savings": "$2250.00", "checking": "$900.50"},
    "77777": {"name": "Dana Okoro", "savings": "$9,420.00", "checking": "$1,105.40"},
    "66666": {"name": "Robert Chen", "savings": "$3,100.00", "checking": "$840.25"},
    "55555": {"name": "Alan Reed", "savings": "$4,015.75", "checking": "$620.30"},
    "55550": {"name": "Priya Nair", "savings": "$7,880.10", "checking": "$2,415.00"},
}

VISIBLE_MEMBER_IDS = ("12345", "67890")
VISIBLE_MEMBERS = {}
for member_id in VISIBLE_MEMBER_IDS:
    VISIBLE_MEMBERS[member_id] = MEMBERS[member_id]


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"members": VISIBLE_MEMBERS}
    )


@app.post("/lookup")
async def lookup_member(request: Request, member_id: str = Form(...)):
    if member_id == "88888":
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "members": VISIBLE_MEMBERS,
                "error_message": "Permission denied",
                "status_code": "PERMISSION_DENIED",
            },
            status_code=403,
        )

    if member_id == "77777" and request.cookies.get("slow_lookup_complete") != "true":
        await asyncio.sleep(6)
        response = RedirectResponse(url="/member/77777", status_code=303)
        response.set_cookie(key="slow_lookup_complete", value="true", httponly=True, samesite="lax")
        return response

    if member_id == "66666" and request.cookies.get("session_restored") != "true":
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "members": VISIBLE_MEMBERS,
                "error_message": "Session expired. Please sign in again.",
                "status_code": "SESSION_EXPIRED",
                "show_restore": True,
            },
        )

    if member_id == "55555" and request.cookies.get("notice_acknowledged") != "true":
        return templates.TemplateResponse(
            request=request,
            name="interstitial.html",
            context={
                "heading": "System Notice",
                "button_text": "Continue",
                "action": "/interstitial/55555/continue",
            },
        )

    if member_id == "55550":
        return templates.TemplateResponse(
            request=request,
            name="interstitial.html",
            context={
                "heading": "Security Verification Required",
                "button_text": "Verify Identity",
                "action": "/interstitial/55550/verify",
            },
        )

    member = MEMBERS.get(member_id)

    if member is None:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "members": VISIBLE_MEMBERS,
                "error_message": "No member found",
                "status_code": "MEMBER_NOT_FOUND",
            },
        )

    return RedirectResponse(url=f"/member/{member_id}", status_code=303)


@app.post("/session/restore")
async def restore_session():
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session_restored", value="true", httponly=True, samesite="lax")
    return response


@app.post("/interstitial/55555/continue")
async def continue_from_known_interstitial():
    response = RedirectResponse(url="/member/55555", status_code=303)
    response.set_cookie(key="notice_acknowledged", value="true", httponly=True, samesite="lax")
    return response


@app.post("/interstitial/55550/verify")
async def verify_identity():
    return RedirectResponse(url="/member/55550", status_code=303)


@app.get("/member/{member_id}")
async def member_details(request: Request, member_id: str):
    member = MEMBERS.get(member_id)

    if member is None:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "members": VISIBLE_MEMBERS,
                "error_message": "No member found",
                "status_code": "MEMBER_NOT_FOUND",
            },
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request, name="member.html", context={"member_id": member_id, "member": member}
    )


@app.get("/legacy-lookup")
async def legacy_lookup(request: Request):
    return templates.TemplateResponse(request=request, name="legacy_lookup.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
