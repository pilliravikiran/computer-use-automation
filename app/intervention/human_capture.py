"""Best-effort capture of actions performed during human control."""

import json

from playwright.async_api import ConsoleMessage

from app.models.intervention import HumanAction
from app.runs.session import RunSession
from app.surfaces.web_playwright import WebSurfaceAdapter

MESSAGE_PREFIX = "HUMAN_ACTION:"

CAPTURE_SCRIPT = """
(() => {
    if (window.__humanActionCaptureInstalled) return;
    window.__humanActionCaptureInstalled = true;

    const record = (event) => {
        const element = event.target;
        if (!(element instanceof Element)) return;

        console.log("HUMAN_ACTION:" + JSON.stringify({
            action: event.type,
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute("role") || element.tagName.toLowerCase(),
            name: element.getAttribute("aria-label")
                || element.innerText?.trim()
                || element.getAttribute("name")
                || "",
            timestamp: new Date().toISOString()
        }));
    };

    ["click", "input", "change"].forEach((eventName) => {
        document.addEventListener(eventName, record, true);
    });
})();
"""


class HumanActionCapture:
    """Install capture once and append browser messages to the run session."""

    def __init__(self) -> None:
        self.installed_page_ids: set[int] = set()

    async def install(self, session: RunSession) -> None:
        """Capture the current page and pages created by future navigation."""
        if not isinstance(session.surface, WebSurfaceAdapter):
            raise TypeError("Human capture currently requires a web surface")
        if session.surface.page is None:
            raise RuntimeError("The web surface has no open page")

        page = session.surface.page
        page_id = id(page)
        if page_id in self.installed_page_ids:
            return

        def record_message(message: ConsoleMessage) -> None:
            if not message.text.startswith(MESSAGE_PREFIX):
                return

            data = json.loads(message.text.removeprefix(MESSAGE_PREFIX))
            session.human_actions.append(HumanAction.model_validate(data))

        page.on("console", record_message)
        await page.add_init_script(script=CAPTURE_SCRIPT)
        await page.evaluate(CAPTURE_SCRIPT)
        self.installed_page_ids.add(page_id)
