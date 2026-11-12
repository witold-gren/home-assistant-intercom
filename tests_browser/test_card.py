"""The card in Google Chrome: a fake Home Assistant, Chrome's fake microphone."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright
import pytest

CARD = Path(__file__).parent.parent / "custom_components/intercom/frontend/intercom-card.js"
PAGE = "http://localhost/intercom-test.html"

# A Home Assistant just big enough for the card: its calls are recorded in window.calls
FAKE_HASS = """
customElements.define("home-assistant", class extends HTMLElement {});
window.calls = [];
window.hass = {
  language: "pl",
  areas: { living_room: { name: "Salon" } },
  connection: {
    sendMessagePromise: async (message) => {
      window.calls.push(message);
      if (message.type === "intercom/rooms") {
        return { rooms: [{ area: "living_room", name: "Salon", ready: true }, { area: "kitchen", name: "Kuchnia", ready: true }] };
      }
      return { response: { played: [{ area: "living_room" }], missing: [] } };
    },
  },
  fetchWithAuth: async (url, init) => {
    window.calls.push({ url, type: init.headers["Content-Type"], size: init.body.size });
    return new Response(JSON.stringify({ played: [{ area: "living_room" }], missing: [] }), { status: 200 });
  },
};
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
        )
        yield instance
        instance.close()


def open_card(browser: Browser, config: dict, microphone: bool = True) -> Page:
    context = browser.new_context(permissions=["microphone"] if microphone else [])
    page = context.new_page()
    # localhost is a secure page: the microphone is allowed there, as over https
    page.route(PAGE, lambda route: route.fulfill(content_type="text/html", body="<body></body>"))
    page.goto(PAGE)
    page.add_script_tag(content=FAKE_HASS)
    if not microphone:
        page.add_script_tag(
            content="Object.defineProperty(navigator, 'mediaDevices', { value: undefined });"
        )
    page.add_script_tag(path=str(CARD))
    page.wait_for_function("() => customElements.get('intercom-card')")
    page.evaluate(
        """(config) => {
            const card = document.createElement("intercom-card");
            card.setConfig(config);
            card.hass = window.hass;
            document.body.appendChild(card);
        }""",
        config,
    )
    return page


def test_a_room_card_records_and_sends_a_wav(browser: Browser) -> None:
    page = open_card(browser, {"areas": ["living_room"]})
    card = page.locator("intercom-card")
    assert card.locator(".name").inner_text() == "Salon"
    assert card.locator(".sub").inner_text() == "Interkom"
    card.locator("ha-card").click()
    sheet = page.locator("intercom-sheet")
    assert sheet.locator("h2").inner_text() == "Do: Salon"
    sheet.locator(".stop").wait_for()
    # The live wave follows the voice of the fake microphone
    page.wait_for_timeout(1200)
    assert sheet.locator(".wave i").count() == 56
    sheet.locator(".stop").click()
    page.wait_for_function("() => window.calls.some((c) => c.url)")
    sent = page.evaluate("window.calls.find((c) => c.url)")
    assert sent["url"] == "/api/intercom/message?areas=living_room"
    assert sent["type"] == "audio/wav"
    assert sent["size"] > 44
    sheet.locator(".badge.ok + .label", has_text="Wysłano").wait_for()
    # The window closes by itself
    sheet.wait_for(state="detached")


def test_without_a_microphone_the_message_is_typed(browser: Browser) -> None:
    page = open_card(browser, {"areas": ["living_room"], "name": "Salon"}, microphone=False)
    page.locator("intercom-card ha-card").click()
    sheet = page.locator("intercom-sheet")
    assert "wpisz wiadomość" in sheet.locator(".note").inner_text()
    sheet.locator("input").fill("Obiad!")
    sheet.locator("button.send").click()
    page.wait_for_function("() => window.calls.some((c) => c.type === 'call_service')")
    call = page.evaluate("window.calls.find((c) => c.type === 'call_service')")
    assert call["domain"] == "intercom" and call["service"] == "announce"
    assert call["service_data"] == {"areas": ["living_room"], "message": "Obiad!"}
    assert call["return_response"] is True


def test_the_whole_house_asks_for_the_rooms(browser: Browser) -> None:
    page = open_card(browser, {}, microphone=False)
    assert page.locator("intercom-card .name").inner_text() == "Dom"
    page.locator("intercom-card ha-card").click()
    page.locator("intercom-sheet input").fill("Kolacja")
    page.locator("intercom-sheet button.send").click()
    page.wait_for_function("() => window.calls.some((c) => c.type === 'call_service')")
    call = page.evaluate("window.calls.find((c) => c.type === 'call_service')")
    assert call["service_data"]["areas"] == ["living_room", "kitchen"]


def test_closing_cancels(browser: Browser) -> None:
    page = open_card(browser, {"areas": ["living_room"]})
    page.locator("intercom-card ha-card").click()
    page.locator("intercom-sheet .stop").wait_for()
    page.locator("intercom-sheet .close").click()
    assert page.locator("intercom-sheet").count() == 0
    assert page.evaluate("window.calls.filter((c) => c.url).length") == 0


def test_the_window_fits_a_phone(browser: Browser) -> None:
    page = open_card(browser, {"areas": ["living_room"]})
    page.set_viewport_size({"width": 360, "height": 640})
    page.locator("intercom-card ha-card").click()
    page.locator("intercom-sheet .stop").wait_for()
    box = page.evaluate(
        """() => {
            const r = document.querySelector("intercom-sheet").shadowRoot
              .querySelector(".card").getBoundingClientRect();
            return { left: r.left, right: r.right };
        }"""
    )
    assert box["left"] >= 0 and box["right"] <= 360, box


def test_recording_goes_on_after_done(browser: Browser) -> None:
    """The last syllable is often said as Done is tapped: the recording keeps a short tail."""
    page = open_card(browser, {"areas": ["living_room"]})
    page.locator("intercom-card ha-card").click()
    sheet = page.locator("intercom-sheet")
    sheet.locator(".stop").wait_for()
    page.wait_for_timeout(1200)
    sheet.locator(".stop").click()
    page.wait_for_function("() => window.calls.some((c) => c.url)")
    size = page.evaluate("window.calls.find((c) => c.url).size")
    seconds = (size - 44) / 2 / 24000  # the card's WAV: 24 kHz mono 16-bit
    assert seconds >= 1.6, f"{seconds:.2f} s recorded"
