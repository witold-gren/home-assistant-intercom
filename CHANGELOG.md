# Changelog

## 0.1.5

- The voice step also shows for an engine that knows the language only by its full code (Piper
  offers its voices for `pl_PL` while Home Assistant's language is `pl`).

## 0.1.4

- The voice of the text-to-speech engine for typed messages (and the HomePods), when the engine
  offers more than one: a step after *Voice and recordings*.
- The options show the rooms with their speakers, and a room is chosen from that list (or another
  area to add) instead of an empty area field.

## 0.1.3

- The end of a message is no longer cut off on a HomePod: whole-file speakers get WAV messages
  (recordings and spoken text) with 2 s of silence at their end. Over AirPlay the stream was closed
  about 1.5 s after the last sound while the HomePod still held up to 2 s in its buffer.

## 0.1.2

- Better rooms when the integration is added: voice satellites first (made for announcements), then
  media players; televisions and a satellite's own media player are left out, and Apple TV players
  (HomePods) get whole files by themselves.

## 0.1.1

- A whole-file speaker that is off is passed over for the room's next speaker: Apple TV shows a
  HomePod it lost as off and plays nothing on it, without an error. Other players that are off
  (a Google speaker at rest) still play.

## 0.1.0

First version.

- `intercom.announce`: speaks a text or plays a recording in rooms, each on the first of its
  speakers that is up; answers where it was heard and which rooms were missed.
- Rooms set up by themselves from the areas' media players and voice satellites; in the options a
  room's speakers in order, the speakers that get a whole file (Apple TV / HomePod), the volume of
  messages; the text-to-speech engine, its language and how long messages are kept.
- `POST /api/intercom/message`: a recording from a browser, for any signed-in user; kept in the
  integration's folder and removed after 15 minutes.
- `custom:intercom-card`: a button that records a message in a window like a phone's intercom, with
  the live wave of the voice; a text field without a microphone.
- Voice assistant: with Assist Router 0.1.5+ "Announcement to the kitchen, ..." plays in the rooms
  named (or every room but the one spoken in), in the speaker's own voice with Assist Speaker ID.
  `custom_components.intercom.api` for other integrations: `is_set_up`, `areas_in_text`,
  `async_announce`.
- Translations: English, Polish.
