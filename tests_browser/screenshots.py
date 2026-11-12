"""The screenshots of the README: the card while speaking and once sent, in English and Polish.

Google Chrome with its fake microphone (a beeping tone moves the wave) and the fake Home
Assistant of the tests; run with `make screenshots`.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright
from test_card import CARD, FAKE_HASS, PAGE

IMAGES = Path(__file__).parent.parent / "images"

# A phone, and a dashboard's background behind the window
VIEWPORT = {"width": 390, "height": 640}
BACKGROUND = "<body style='margin:0;padding:16px;background:#e9eaee'></body>"


def shoot(browser, language: str) -> None:
    context = browser.new_context(
        permissions=["microphone"], viewport=VIEWPORT, device_scale_factor=2
    )
    page = context.new_page()
    page.route(PAGE, lambda route: route.fulfill(content_type="text/html", body=BACKGROUND))
    page.goto(PAGE)
    page.add_script_tag(content=FAKE_HASS.replace('language: "pl"', f'language: "{language}"'))
    page.add_script_tag(path=str(CARD))
    page.wait_for_function("() => customElements.get('intercom-card')")
    page.evaluate(
        """(name) => {
            const card = document.createElement("intercom-card");
            card.setConfig({ areas: ["living_room"], name });
            card.hass = window.hass;
            document.body.appendChild(card);
        }""",
        "Salon" if language == "pl" else "Living room",
    )
    page.locator("intercom-card ha-card").click()
    sheet = page.locator("intercom-sheet")
    sheet.locator(".stop").wait_for()
    # A few seconds of voice: the counter runs and the wave fills
    page.wait_for_timeout(3200)
    page.screenshot(path=IMAGES / f"speaking-{language}.png")
    sheet.locator(".stop").click()
    sheet.locator(
        ".badge.ok + .label", has_text="Wysłano" if language == "pl" else "Sent"
    ).wait_for()
    page.screenshot(path=IMAGES / f"sent-{language}.png")
    context.close()


def main() -> None:
    IMAGES.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
        )
        for language in ("en", "pl"):
            shoot(browser, language)
        browser.close()
    print(f"Screenshots in {IMAGES}")


if __name__ == "__main__":
    main()
