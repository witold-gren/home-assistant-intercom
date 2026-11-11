# Changelog

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
- Translations: English, Polish.
