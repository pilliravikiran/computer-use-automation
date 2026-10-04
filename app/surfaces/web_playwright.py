"""Playwright implementation of the surface adapter."""

import re
from pathlib import Path

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.models.artifacts import ExtractMode
from app.models.errors import LowConfidenceTargetError
from app.models.observations import ElementObservation, Observation
from app.models.targets import Locator as SavedLocator
from app.models.targets import TargetStrategy
from app.surfaces.base import SurfaceAdapter


class WebSurfaceAdapter(SurfaceAdapter):
    """Control a web application through asynchronous Playwright."""

    def __init__(self, headless: bool) -> None:
        self.headless = headless
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._refs: dict[str, Locator] = {}

    async def open(self, target: str) -> None:
        """Start Playwright before opening the target application."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.page.goto(target, wait_until="domcontentloaded")

    async def _get_textbox_name(self, textbox: Locator) -> str:
        """Return a simple user-facing name for one textbox."""
        if self.page is None:
            raise RuntimeError("The web surface must be opened first")

        element_id = await textbox.get_attribute("id")
        if element_id is not None:
            labels = self.page.locator(f'label[for="{element_id}"]')
            if await labels.count() > 0:
                return (await labels.first.inner_text()).strip()

        aria_label = await textbox.get_attribute("aria-label")
        if aria_label is not None:
            return aria_label.strip()

        placeholder = await textbox.get_attribute("placeholder")
        if placeholder is not None:
            return placeholder.strip()

        return ""

    async def observe(self) -> Observation:
        """Return a compact structured view of the current webpage."""
        if self.page is None:
            raise RuntimeError("The web surface must be opened before observation")

        self._refs.clear()
        elements: list[ElementObservation] = []
        next_ref_number = 1

        textboxes = self.page.get_by_role("textbox")
        textbox_count = await textboxes.count()
        for position in range(textbox_count):
            textbox = textboxes.nth(position)
            ref = f"e{next_ref_number}"
            name = await self._get_textbox_name(textbox)

            elements.append(ElementObservation(ref=ref, role="textbox", name=name))
            self._refs[ref] = textbox
            next_ref_number += 1

        buttons = self.page.get_by_role("button")
        button_count = await buttons.count()
        for position in range(button_count):
            button = buttons.nth(position)
            ref = f"e{next_ref_number}"
            name = (await button.inner_text()).strip()

            elements.append(ElementObservation(ref=ref, role="button", name=name))
            self._refs[ref] = button
            next_ref_number += 1

        rowheaders = self.page.get_by_role("rowheader")
        rowheader_count = await rowheaders.count()
        for position in range(rowheader_count):
            rowheader = rowheaders.nth(position)
            ref = f"e{next_ref_number}"
            name = (await rowheader.inner_text()).strip()

            elements.append(ElementObservation(ref=ref, role="rowheader", name=name))
            self._refs[ref] = rowheader
            next_ref_number += 1

        return Observation(
            url=self.page.url,
            title=await self.page.title(),
            text=(await self.page.locator("body").inner_text()).strip(),
            elements=elements,
        )

    async def resolve_target(self, ref: str) -> Locator:
        """Return the Playwright locator for a temporary reference."""
        try:
            return self._refs[ref]
        except KeyError as error:
            raise ValueError(f"Unknown or expired target reference: {ref}") from error

    async def find(self, locator: SavedLocator) -> Locator | None:
        """Find exactly one element using a saved locator strategy."""
        if self.page is None:
            raise RuntimeError("The web surface must be opened first")

        if locator.strategy is TargetStrategy.ROLE_NAME:
            candidate = self.page.get_by_role(locator.role, name=locator.value, exact=True)
        elif locator.strategy is TargetStrategy.LABEL:
            candidate = self.page.get_by_label(locator.value, exact=True)
        elif locator.strategy is TargetStrategy.TEXT:
            candidate = self.page.get_by_text(locator.value, exact=True)
        elif locator.strategy is TargetStrategy.ATTRIBUTE:
            candidate = self.page.locator(f'[{locator.attribute}="{locator.value}"]')
        else:
            candidate = self.page.locator(locator.value)

        match_count = await candidate.count()
        if match_count == 0:
            return None
        if match_count > 1:
            raise LowConfidenceTargetError(f"Locator matched {match_count} elements")

        return candidate

    async def type(self, ref: str, value: str) -> None:
        """Fill a referenced web element with text."""
        target = await self.resolve_target(ref)
        await target.fill(value)

    async def click(self, ref: str) -> None:
        """Click a referenced web element."""
        target = await self.resolve_target(ref)
        await target.click()

    async def type_element(self, element: object, value: str, timeout_ms: int) -> None:
        """Fill an already-resolved Playwright element."""
        if not isinstance(element, Locator):
            raise TypeError("Expected a Playwright Locator")
        try:
            await element.fill(value, timeout=timeout_ms)
        except PlaywrightTimeoutError as error:
            raise TimeoutError("Typing exceeded the step timeout") from error

    async def click_element(self, element: object, timeout_ms: int) -> None:
        """Click an already-resolved Playwright element."""
        if not isinstance(element, Locator):
            raise TypeError("Expected a Playwright Locator")
        try:
            await element.click(timeout=timeout_ms)
        except PlaywrightTimeoutError as error:
            raise TimeoutError("Clicking exceeded the step timeout") from error

    async def extract_text(self, element: object, mode: ExtractMode, timeout_ms: int) -> str:
        """Read text according to the artifact's extraction mode."""
        if not isinstance(element, Locator):
            raise TypeError("Expected a Playwright Locator")

        if mode is ExtractMode.SELF:
            try:
                return (await element.inner_text(timeout=timeout_ms)).strip()
            except PlaywrightTimeoutError as error:
                raise TimeoutError("Extraction exceeded the step timeout") from error

        if mode in {ExtractMode.ADJACENT_CELL, ExtractMode.LABELLED_VALUE}:
            value_element = element.locator("xpath=following-sibling::td[1]")
        else:
            value_element = element.locator("xpath=following-sibling::*[1]")

        if await value_element.count() != 1:
            raise LookupError("Could not find one extractable value")

        try:
            return (await value_element.inner_text(timeout=timeout_ms)).strip()
        except PlaywrightTimeoutError as error:
            raise TimeoutError("Extraction exceeded the step timeout") from error

    async def close(self) -> None:
        """Release resources owned by this web surface."""
        if self.page is not None:
            await self.page.close()
            self.page = None
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None

    async def capture_failure_evidence(self, directory: Path, name: str) -> Path | None:
        """Save redacted HTML structure without credentials, values, or PII."""
        if self.page is None:
            return None
        directory.mkdir(parents=True, exist_ok=True)
        html = await self.page.content()
        html = re.sub(
            r"(<td[^>]*>).*?(</td>)", r"\1[REDACTED]\2", html, flags=re.IGNORECASE | re.DOTALL
        )
        html = re.sub(r"\$[\d,]+(?:\.\d{2})?", "[REDACTED_AMOUNT]", html)
        html = re.sub(r"\b\d{4,}\b", "[REDACTED_ID]", html)
        path = directory / f"{name}-redacted-dom.html"
        path.write_text(html, encoding="utf-8")
        return path
