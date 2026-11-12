// Intercom card: a button that records a voice message and speaks it in rooms (the Intercom
// integration). The window looks like a phone's intercom: who it goes to, the live wave of the
// voice, a stop button that sends. Without a microphone (a page over http) a text field takes over.
//
//   type: custom:intercom-card
//   areas: [living_room]   # optional; without it the whole house (every room of the integration)
//   name: Living room      # optional
//   icon: mdi:account-voice
(() => {
  const VERSION = "0.1.0";
  const MAX_SECONDS = 30;
  const MIN_SECONDS = 0.8;
  const SAMPLE_RATE = 24000;
  const MAX_GAIN = 4;
  const TARGET_PEAK = 0.9;
  const WAVE_BARS = 56;
  const WAVE_STEP_MS = 70;
  const CLOSE_DELAY_MS = 2000;

  const TEXTS = {
    en: {
      intercom: "Intercom",
      to: "To: {name}",
      house: "Home",
      done: "Done",
      send: "Send",
      cancel: "Cancel",
      starting: "Turning on the microphone…",
      sending: "Sending…",
      sent: "Sent",
      too_short: "Too short, hold on a little longer",
      no_mic: "No microphone here: type the message",
      no_speaker: "No speaker answered",
      failed: "Not sent: {reason}",
      text: "Message",
      missing: "Not heard in: {rooms}",
    },
    pl: {
      intercom: "Interkom",
      to: "Do: {name}",
      house: "Dom",
      done: "Gotowe",
      send: "Wyślij",
      cancel: "Anuluj",
      starting: "Włączam mikrofon…",
      sending: "Wysyłam…",
      sent: "Wysłano",
      too_short: "Za krótko, mów trochę dłużej",
      no_mic: "Tu nie ma mikrofonu: wpisz wiadomość",
      no_speaker: "Żaden głośnik nie odpowiedział",
      failed: "Nie wysłano: {reason}",
      text: "Wiadomość",
      missing: "Nie usłyszą w: {rooms}",
    },
  };

  function t(hass, key, values = {}) {
    const language = (hass?.language || "en").split("-")[0];
    const text = (TEXTS[language] || TEXTS.en)[key] ?? TEXTS.en[key] ?? key;
    return text.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? "");
  }

  function writeText(view, offset, text) {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  }

  // Float32 chunks to mono 16-bit WAV, normalised because phone microphones are quiet.
  function encodeWav(chunks, inputRate) {
    const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
    const input = new Float32Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      input.set(chunk, offset);
      offset += chunk.length;
    }
    const ratio = inputRate / SAMPLE_RATE;
    const outputLength = Math.floor(length / ratio);
    const samples = new Float32Array(outputLength);
    let peak = 0;
    for (let index = 0; index < outputLength; index += 1) {
      const position = index * ratio;
      const start = Math.floor(position);
      const fraction = position - start;
      samples[index] = input[start] * (1 - fraction) + (input[start + 1] ?? 0) * fraction;
      peak = Math.max(peak, Math.abs(samples[index]));
    }
    const gain = peak > 0 ? Math.min(MAX_GAIN, TARGET_PEAK / peak) : 1;
    const buffer = new ArrayBuffer(44 + outputLength * 2);
    const view = new DataView(buffer);
    writeText(view, 0, "RIFF");
    view.setUint32(4, 36 + outputLength * 2, true);
    writeText(view, 8, "WAVEfmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, SAMPLE_RATE, true);
    view.setUint32(28, SAMPLE_RATE * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeText(view, 36, "data");
    view.setUint32(40, outputLength * 2, true);
    for (let index = 0; index < outputLength; index += 1) {
      const sample = Math.max(-1, Math.min(1, samples[index] * gain));
      view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  function canRecord() {
    return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia);
  }

  class VoiceRecorder {
    // Made inside the tap: after an await, iOS keeps the audio context suspended and records nothing.
    constructor() {
      const Context = window.AudioContext ?? window.webkitAudioContext;
      this.context = new Context();
      this.resumed = this.context.resume().catch(() => {});
    }

    async start() {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      await Promise.race([this.resumed, new Promise((resolve) => setTimeout(resolve, 1000))]);
      if (!this.context) return;
      const source = this.context.createMediaStreamSource(this.stream);
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 1024;
      this.samples = new Float32Array(this.analyser.fftSize);
      source.connect(this.analyser);
      this.processor = this.context.createScriptProcessor(4096, 1, 1);
      this.chunks = [];
      this.processor.onaudioprocess = (event) => this.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      source.connect(this.processor);
      // iOS only fires the callback on a connected node; nothing reaches the speakers.
      this.processor.connect(this.context.destination);
      this.startedAt = Date.now();
    }

    level() {
      if (!this.analyser) return 0;
      this.analyser.getFloatTimeDomainData(this.samples);
      let sum = 0;
      for (const sample of this.samples) sum += sample * sample;
      return Math.min(1, Math.sqrt(sum / this.samples.length) * 6);
    }

    get seconds() {
      return this.startedAt ? (Date.now() - this.startedAt) / 1000 : 0;
    }

    stop() {
      const rate = this.context?.sampleRate;
      const { chunks } = this;
      const seconds = this.seconds;
      this.cancel();
      return seconds >= MIN_SECONDS && chunks?.length ? encodeWav(chunks, rate) : null;
    }

    cancel() {
      if (this.processor) {
        this.processor.onaudioprocess = null;
        this.processor.disconnect();
      }
      this.stream?.getTracks().forEach((track) => track.stop());
      this.context?.close().catch(() => {});
      this.processor = null;
      this.analyser = null;
      this.stream = null;
      this.context = null;
    }
  }

  const SHEET_STYLE = `
    :host { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 16px;
      background: rgba(0, 0, 0, 0.35); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px);
      font-family: var(--paper-font-body1_-_font-family, -apple-system, system-ui, sans-serif); }
    .card { position: relative; width: min(420px, calc(100vw - 32px)); min-height: 420px; display: flex; flex-direction: column;
      align-items: center; box-sizing: border-box; padding: 56px 24px 28px; border-radius: 32px;
      background: #ffffff; color: #111; box-shadow: 0 24px 60px rgba(0, 0, 0, 0.25); }
    .close { position: absolute; top: 18px; right: 18px; width: 44px; height: 44px; border-radius: 50%;
      border: 1px solid #e3e3e6; background: #f6f6f7; color: #111; font-size: 22px; line-height: 1; cursor: pointer; }
    h2 { margin: 0; font-size: 30px; font-weight: 700; text-align: center; }
    .sub { margin-top: 4px; color: #8a8a8e; font-size: 17px; }
    .wave { flex: 1; width: 100%; overflow: hidden; display: flex; align-items: center; justify-content: center; gap: 3px; min-height: 140px; }
    .wave i { display: block; width: 3px; border-radius: 2px; background: #111; }
    .wave i.dot { width: 3px; height: 3px; background: #9a9aa0; }
    .note { min-height: 20px; margin: 4px 0 12px; color: #8a8a8e; font-size: 15px; text-align: center; }
    .stop { width: 76px; height: 76px; border-radius: 50%; border: 0; background: #f0913e; cursor: pointer;
      display: grid; place-items: center; box-shadow: 0 2px 8px rgba(240, 145, 62, 0.4); }
    .stop span { width: 22px; height: 22px; border-radius: 4px; background: #fff; }
    .stop[disabled] { opacity: 0.5; cursor: default; }
    .badge { width: 76px; height: 76px; border-radius: 50%; display: grid; place-items: center; color: #fff;
      font-size: 34px; font-weight: 600; line-height: 1; }
    .badge.busy { background: #c7c7cc; font-size: 22px; letter-spacing: 3px; }
    .badge.ok { background: #34c759; box-shadow: 0 2px 8px rgba(52, 199, 89, 0.4); }
    .badge.busy span { animation: pulse 1s ease-in-out infinite; }
    @keyframes pulse { 50% { opacity: 0.35; } }
    .action { width: 100%; display: flex; flex-direction: column; align-items: center; }
    .label { margin-top: 10px; color: #8a8a8e; font-size: 16px; }
    form { width: 100%; display: flex; gap: 8px; }
    input { flex: 1; min-width: 0; padding: 12px 14px; border-radius: 14px; border: 1px solid #d8d8dc; font: inherit; }
    button.send { padding: 0 18px; border-radius: 14px; border: 0; background: #f0913e; color: #fff; font: inherit; cursor: pointer; }
    @media (prefers-color-scheme: dark) {
      .card { background: #1c1c1e; color: #f2f2f7; }
      .close { background: #2c2c2e; border-color: #3a3a3c; color: #f2f2f7; }
      .wave i { background: #f2f2f7; }
      input { background: #2c2c2e; color: #f2f2f7; border-color: #3a3a3c; }
    }`;

  // Built from the current window.HTMLElement once the frontend has set up its element registry (a
  // card defined at once, from a module the frontend loads first, lands in the old registry and
  // shows as "Custom element doesn't exist").
  function defineElements() {
  class IntercomSheet extends window.HTMLElement {
    open(hass, areas, name) {
      this.hass = hass;
      this.areas = areas;
      this.name = name;
      this.levels = [];
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${SHEET_STYLE}</style>
        <div class="card" role="dialog" aria-modal="true">
          <button class="close" aria-label="${t(hass, "cancel")}">✕</button>
          <h2>${t(hass, "to", { name: this.escape(name) })}</h2>
          <div class="sub">${t(hass, "intercom")}</div>
          <div class="wave"></div>
          <div class="note"></div>
          <div class="action"></div>
        </div>`;
      this.shadowRoot.querySelector(".close").addEventListener("click", () => this.close());
      // Only a tap on the backdrop itself closes: a tap inside the card is retargeted to this host too
      this.addEventListener("click", (event) => event.composedPath()[0] === this && this.close());
      document.body.appendChild(this);
      if (canRecord()) this.record();
      else this.textMode(t(hass, "no_mic"));
    }

    escape(text) {
      const span = document.createElement("span");
      span.textContent = text;
      return span.innerHTML;
    }

    note(text) {
      this.shadowRoot.querySelector(".note").textContent = text || "";
    }

    async record() {
      this.recorder = new VoiceRecorder();
      this.note(t(this.hass, "starting"));
      try {
        await this.recorder.start();
      } catch {
        this.recorder.cancel();
        this.recorder = null;
        this.textMode(t(this.hass, "no_mic"));
        return;
      }
      this.note("");
      this.shadowRoot.querySelector(".action").innerHTML =
        `<button class="stop" aria-label="${t(this.hass, "done")}"><span></span></button><div class="label">${t(this.hass, "done")}</div>`;
      this.shadowRoot.querySelector(".stop").addEventListener("click", () => this.finish());
      this.waver = setInterval(() => {
        this.levels.push(this.recorder?.level() ?? 0);
        if (this.levels.length > WAVE_BARS) this.levels.shift();
        this.drawWave();
        if ((this.recorder?.seconds ?? 0) >= MAX_SECONDS) this.finish();
      }, WAVE_STEP_MS);
    }

    drawWave() {
      const bars = [...Array(Math.max(0, WAVE_BARS - this.levels.length)).fill(0), ...this.levels];
      this.shadowRoot.querySelector(".wave").innerHTML = bars
        .map((level) => (level < 0.04 ? '<i class="dot"></i>' : `<i style="height:${Math.round(8 + level * 72)}px"></i>`))
        .join("");
    }

    async finish() {
      clearInterval(this.waver);
      const blob = this.recorder?.stop();
      this.recorder = null;
      if (!blob) {
        this.note(t(this.hass, "too_short"));
        setTimeout(() => this.record(), 900);
        return;
      }
      this.send(async () => {
        const query = encodeURIComponent(this.areas.join(","));
        const response = await this.hass.fetchWithAuth(`/api/intercom/message?areas=${query}`, {
          method: "POST",
          headers: { "Content-Type": "audio/wav" },
          body: blob,
        });
        const answer = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(answer.message || response.statusText);
        return answer;
      });
    }

    textMode(note) {
      clearInterval(this.waver);
      this.note(note);
      this.shadowRoot.querySelector(".wave").innerHTML = "";
      this.shadowRoot.querySelector(".action").innerHTML =
        `<form><input enterkeyhint="send" autocomplete="off" placeholder="${t(this.hass, "text")}" /><button class="send">${t(this.hass, "send")}</button></form>`;
      const input = this.shadowRoot.querySelector("input");
      setTimeout(() => input.focus(), 50);
      this.shadowRoot.querySelector("form").addEventListener("submit", (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message) return;
        this.send(async () => {
          const result = await this.hass.connection.sendMessagePromise({
            type: "call_service",
            domain: "intercom",
            service: "announce",
            service_data: { areas: this.areas, message },
            return_response: true,
          });
          return result?.response ?? {};
        });
      });
    }

    status(kind, mark, label) {
      this.shadowRoot.querySelector(".action").innerHTML =
        `<div class="badge ${kind}" aria-hidden="true"><span>${mark}</span></div><div class="label">${label}</div>`;
    }

    async send(deliver) {
      this.note("");
      this.status("busy", "•••", t(this.hass, "sending"));
      try {
        const result = await deliver();
        if (!result.played?.length) throw new Error(t(this.hass, "no_speaker"));
        const missing = (result.missing ?? []).length;
        this.status("ok", "✓", t(this.hass, "sent"));
        if (missing) this.note(t(this.hass, "missing", { rooms: result.missing.join(", ") }));
        setTimeout(() => this.close(), missing ? CLOSE_DELAY_MS * 2 : CLOSE_DELAY_MS);
      } catch (error) {
        this.shadowRoot.querySelector(".action").innerHTML = "";
        this.note(t(this.hass, "failed", { reason: error?.message ?? error }));
      }
    }

    close() {
      clearInterval(this.waver);
      this.recorder?.cancel();
      this.remove();
    }
  }

  class IntercomCard extends window.HTMLElement {
    setConfig(config) {
      this.config = { icon: "mdi:account-voice", ...config };
      this.render();
    }

    set hass(hass) {
      this._hass = hass;
      if (!this.rendered) this.render();
    }

    getCardSize() {
      return 1;
    }

    static getStubConfig() {
      return {};
    }

    async areas() {
      if (this.config.areas?.length) return this.config.areas;
      const answer = await this._hass.connection.sendMessagePromise({ type: "intercom/rooms" });
      return (answer.rooms ?? []).map((room) => room.area);
    }

    label() {
      if (this.config.name) return this.config.name;
      const areas = this.config.areas ?? [];
      if (areas.length === 1) return this._hass?.areas?.[areas[0]]?.name ?? areas[0];
      return t(this._hass, "house");
    }

    render() {
      if (!this.config) return;
      if (!this.shadowRoot) this.attachShadow({ mode: "open" });
      this.rendered = Boolean(this._hass);
      this.shadowRoot.innerHTML = `<style>
          ha-card { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }
          .icon { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%;
            background: rgba(240, 145, 62, 0.18); color: #f0913e; }
          .name { font-size: 15px; font-weight: 500; }
          .sub { font-size: 13px; color: var(--secondary-text-color); }
        </style>
        <ha-card role="button" tabindex="0">
          <span class="icon"><ha-icon icon="${this.config.icon}"></ha-icon></span>
          <span><div class="name"></div><div class="sub"></div></span>
        </ha-card>`;
      this.shadowRoot.querySelector(".name").textContent = this.label();
      this.shadowRoot.querySelector(".sub").textContent = t(this._hass, "intercom");
      const card = this.shadowRoot.querySelector("ha-card");
      card.addEventListener("click", () => this.start());
      card.addEventListener("keydown", (event) => (event.key === "Enter" || event.key === " ") && this.start());
    }

    // The sheet opens inside the tap (iOS: the audio context must start there); the rooms follow.
    start() {
      const sheet = document.createElement("intercom-sheet");
      const configured = this.config.areas?.length ? this.config.areas : null;
      if (configured) {
        sheet.open(this._hass, configured, this.label());
        return;
      }
      sheet.open(this._hass, [], this.label());
      this.areas().then((areas) => {
        sheet.areas = areas;
      });
    }
  }

  if (!window.customElements.get("intercom-sheet")) window.customElements.define("intercom-sheet", IntercomSheet);
  if (!window.customElements.get("intercom-card")) window.customElements.define("intercom-card", IntercomCard);
  }

  (function waitForFrontend(attempt) {
    if (window.customElements.get("home-assistant") || attempt >= 600) {
      defineElements();
      return;
    }
    setTimeout(() => waitForFrontend(attempt + 1), 50);
  })(0);

  window.customCards = window.customCards || [];
  if (!window.customCards.some((card) => card.type === "intercom-card")) {
    window.customCards.push({
      type: "intercom-card",
      name: "Intercom",
      description: "Record a voice message and speak it in rooms.",
      preview: true,
    });
  }
  console.info(`%c INTERCOM-CARD %c ${VERSION} `, "background:#f0913e;color:#fff", "");
})();
