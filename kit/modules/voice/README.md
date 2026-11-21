# Voice input and output

## 1. What problem does this solve, and when should I use it?

Add explicit microphone capture, playback and a turn-based voice flow to a browser application. The server can transcribe completed recordings, stream transcript deltas while a completed file is processed, and synthesize or stream speech. Microphone permission, empty recording, errors and cancellation are visible states. No client import contains provider credentials or a server SDK.

## 2. What is the smallest working example?

```sh
node --import tsx modules/voice/examples/demo.ts
```

This runs a **fixture** turn using authored sample text, not a live recording or transcription. The separate [tone.wav](fixtures/tone.wav) is an original 0.5-second, 440 Hz PCM waveform for audio playback tests; it contains no speech. [transcript.json](fixtures/transcript.json) is synthetic text and is not represented as the tone's transcript. [silence.json](fixtures/silence.json) represents an empty transcription result. All are MIT licensed.

For browser capture, render `VoiceRecorder` from [components.tsx](src/components.tsx). With no callback it records and locally plays audio without any network call. Pass `onRecorded(blob,signal)` to explicitly process the recording after the user selects Process recording.

## 3. How do I add it to a fresh project or an existing project?

Select `voice` from the catalog or preserve `modules/voice`, `packages/runtime` and `packages/contracts` when copying. Install pinned Zod and React from [module.json](module.json). Import `MicrophoneRecorder` from [browser.ts](src/browser.ts) or the React components into client code. Import provider functions from [server.ts](src/server.ts) only in server handlers. Adapt existing audio routes rather than exposing keys to browser code.

## 4. What does the API accept and return?

`MicrophoneRecorder(notify,maxSeconds=60,maxBytes=10000000)` exposes `start`, `stop`, `cancel`, and `dispose`. Notifications use idle/requesting/recording/ready/denied/unsupported/error and include a Blob only when captured. Cancel/dispose invalidate pending permission prompts; late-granted streams are immediately stopped. All tracks and duration timers are released. The browser chooses supported WebM/Opus or MP4 recording formats.

`turnReducer(state,event)` enforces idle → recording → transcribing → thinking → speaking → idle. Silence returns to idle, cancellation resets, and failures enter error. Invalid transitions throw rather than corrupting state. State does not persist recordings/transcripts automatically.

`transcribe(file,filename,{apiKey,model,signal?,fetcher?,timeoutMs?})` sends multipart data to `/v1/audio/transcriptions`, returning `{text,mode:'live',kind:'recorded-file',model}`. `streamTranscription` is an async generator of `{type:'delta'|'done',text,mode:'live',kind:'recorded-file-stream'}`. It handles fragmented UTF-8 SSE frames and requires a final transcript event. This is **completed-file streaming**, not ongoing microphone transcription.

`synthesizeSpeech({text,voice?,format?},options)` returns a Blob with mode and `AI-generated voice` disclosure. `streamSpeech` returns a bounded `ReadableStream<Uint8Array>`, content type, format and disclosure. MP3/WAV/PCM formats are supported; PCM is raw 24 kHz, signed 16-bit little-endian audio with no header. Do not assign raw PCM to a plain audio element. Return MP3/WAV streams through authenticated server endpoints for compatible browser playback. The binary stream forwards cancellation upstream.

## 5. What prerequisites, environment variables, or credentials are needed?

Local examples need Node.js 22+. Recording requires a supported modern browser, a microphone, HTTPS or localhost, and user permission. Live providers require server-side `OPENAI_API_KEY`, an audio-capable `OPENAI_TRANSCRIBE_MODEL`, and `OPENAI_TTS_MODEL`. Models are required configuration, not hard-coded aliases; the official examples currently document `gpt-transcribe` for file transcription and `gpt-4o-mini-tts` for speech. Select a model available to your account and check its supported parameters before use.

To deliberately exercise a local WAV through both live adapters after configuring a test account:

```sh
KIT_ALLOW_LIVE=1 node --import tsx modules/voice/examples/live.ts /absolute/path/recording.wav
```

This incurs provider usage and writes `voice-live-output.mp3` in the current directory. The example requires all three environment names; it never runs as part of ordinary tests or switches to sample responses on error.

## 6. What changes must I make to routes, schema, storage, or UI?

Provide an authenticated upload endpoint with your application rate/usage limit and an audio body limit. Pass the request abort signal into the server adapter. Validate filename extension and MIME type; the adapter accepts mp3/mp4/mpeg/mpga/m4a/wav/webm and caps upload at 20 MB. Render returned errors and retry only after explicit user action. Connect `VoiceRecorder.onRecorded` to that endpoint, forwarding the callback's abort signal; its discard action aborts in-flight processing.

Use `AudioPlayback({blob,label})` for complete recordings/output; it revokes object URLs on cleanup. Label provider-generated playback clearly as AI-generated speech. A streamed MP3/WAV endpoint can supply an audio element's source with normal browser authentication; support/caching/range behavior depends on the host and browser and should be checked in your target environment. No database schema is imposed.

Realtime extension recipe: keep the base turn loop until needed; create a dedicated authenticated server endpoint for a short-lived Realtime credential/session, connect browser audio with the provider's documented WebRTC flow, use client-side voice-activity detection and commit turns explicitly for models that require it, append transcript deltas to a separate state, propagate disconnect/cancel to tracks and transport, and impose duration/rate limits. Never ship a long-lived API key. See the current [Realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription); this recipe is not an implemented continuous realtime adapter.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/voice/tests
```

Checks cover turn ordering/silence/cancel, multipart request shape, provider failures, split UTF-8 SSE, incomplete streams, audio streaming cancellation, absent MediaRecorder, denied microphone, late grant after cancellation, maximum recording duration and track release. Mocked provider bytes are transport fixtures, not playable generated speech. Browser hardware/permission UI must also be checked manually with allow, deny, stop, discard, retry and navigation-away cases.

Implementation: implemented. Observed local verification: `npx tsc --noEmit` passed on the module checkout; `npx eslint modules` passed; `npx vitest run modules/voice/tests` passed (9 tests as part of the combined 35-test module run); `node --import tsx modules/voice/examples/demo.ts` completed without credentials. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Live OpenAI transcription/TTS: **not run**; needs authorized test credentials. Actual microphone hardware and browser codec combinations: not exercised by the Node test suite.

## 8. What does it depend on, and what are its limits?

Zod, React and shared runtime/contracts; no audio native packages. Browser recordings default to 60 seconds/10 MB, configurable to at most 300 seconds/20 MB. Server requests default to 60 seconds, transcript stream <=1 MB, TTS response <=20 MB and text <=4096 characters. No automatic network retries or fixture fallback. Provider model capabilities/usage charges vary; API credentials are separate from coding-assistant subscriptions. Speech accuracy and speech generation are not evaluated by these transport contract tests.

Official request formats checked: [file transcription](https://developers.openai.com/api/docs/guides/speech-to-text), [text to speech](https://developers.openai.com/api/docs/guides/text-to-speech). Original code and fixture text/waveform: MIT; provider terms apply to live output.
