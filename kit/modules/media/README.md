# Image and video input

## 1. What problem does this solve, and when should I use it?

Accept browser images, capture a camera frame, sample timestamped video frames, and optionally analyze images with a real vision provider. Resize/re-encode before sending and display validated object boxes. Local synthetic results and live model responses are explicitly distinct.

## 2. What is the smallest working example?

```sh
node --import tsx modules/media/examples/demo.ts
```

This validates the authored [analysis fixture](fixtures/analysis.json) and shows a video-sampling schedule without accessing a camera or an API. `sampleImageSvg` and `sampleVisionResult` from [index.ts](src/index.ts) describe the same original [shape illustration](fixtures/shapes.svg). Pass a data URL of that SVG to `DetectionOverlay({src,result:sampleVisionResult})`; those boxes are authored, not claimed as model detections.

Render `MediaInput` from [components.tsx](src/components.tsx) to preview local uploads, camera capture and six timestamped video samples. Without callbacks, media stays in the browser.

## 3. How do I add it to a fresh project or an existing project?

Select `media` from the catalog or preserve `modules/media`, shared `packages/runtime` and `packages/contracts` when copying. Install pinned Zod/React versions from [module.json](module.json). Browser code imports [browser.ts](src/browser.ts) or React components; server handlers import [server.ts](src/server.ts). Add callbacks to your existing media upload flow rather than replacing its authentication/storage boundaries.

## 4. What does the API accept and return?

`prepareImage(blob,{maxDimension=1280,maxBytes=8000000,quality=0.85,signal?})` accepts JPEG/PNG/WebP, decodes with ImageBitmap, preserves aspect ratio without upscaling, composites transparency on white and returns `{blob,width,height,mimeType:'image/jpeg',originalBytes}`. Canvas re-encoding strips original metadata. Bitmaps/canvases release resources even on failure; decoded images above 40 megapixels fail.

`sampleVideo(blob,{frames=6,maxDurationSeconds=120,...imageOptions})` accepts MP4/WebM up to 50 MB and returns at most 12 `{timestampSeconds,image}` frames. Timestamps span 0 to just before the end, in video seconds. Seeking/decoding has per-event timeouts. Total encoded frame bytes are capped at 12 MB. It does not upload or continuously analyze a whole video. `captureFrame(video,options)` captures a ready camera video element.

`analyzeImage(image,prompt,{apiKey,model,signal?,fetcher?})` sends an image data URL to OpenAI Responses with strict JSON output, no response storage, a 2000-output-token cap and 60-second timeout. It validates `{summary,detections:[{label,confidence,box:{x,y,width,height}}],mode:'live',model}`. Box coordinates are fractions of image width/height, top-left origin, and must fit within the image. Empty detections are valid. Incomplete output, refusal, invalid JSON/schema, HTTP errors and oversized input fail explicitly.

## 5. What prerequisites, environment variables, or credentials are needed?

Node.js 22+ for examples; modern browser with Canvas/ImageBitmap and relevant video codecs for preprocessing. Camera requires HTTPS or localhost and permission. A `.mp4` extension alone does not guarantee the browser can decode its codec. No ffmpeg, OpenCV or native package is required for the ordinary path.

Live analysis requires server-side `OPENAI_API_KEY` and a configured vision-capable `OPENAI_VISION_MODEL` supporting structured output. The model ID is mandatory configuration. After selecting a test account/model, an explicit live check is:

```sh
KIT_ALLOW_LIVE=1 node --import tsx modules/media/examples/live.ts /absolute/path/image.png
```

This may incur usage. It is excluded from normal tests and never produces a fixture when the provider fails.

## 6. What changes must I make to routes, schema, storage, or UI?

`MediaInput({onImage?,onFrames?})` supplies processed image data or bounded samples; each callback receives an AbortSignal as its second argument. Forward that signal into any provider request so Cancel propagates beyond local decoding. Callback invocation is the boundary where your application can send data; show a clear analysis mode/cost action in the host app when connecting a provider. Add authenticated, rate-limited server uploads with body limits and request cancellation, then call `analyzeImage`. Keep keys only on the server. Do not trust an uploaded filename or the user's claimed MIME type as proof of content; browser decoding/provider validation can reject malformed files, and server-side file scanning may be needed for a storage product.

`DetectionOverlay({src,result})` validates and renders image, boxes, labels and confidence tooltips plus empty/error states. Keep the processed image and matching result together so overlays stay aligned. For video, analyze each selected frame deliberately with bounded concurrency/total frame count; include timestampSeconds with each result. No migration/storage policy is imposed; the module does not automatically retain uploads.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/media/tests
```

Tests cover timestamp planning, count/duration limits, box bounds, empty detections, resize/resource cleanup, unsupported/empty/oversized/cancelled image inputs, Responses request shape, refusal, incomplete output and malformed responses. Camera denial produces a browser-setting recovery message; unsupported codecs/file types and decode timeouts are visible errors. Cancel closes camera tracks and aborts local processing; disposal invalidates pending permission requests and revokes video object URLs.

Implementation: implemented. Observed local verification: `npx tsc --noEmit` passed on the module checkout; `npx eslint modules` passed; `npx vitest run modules/media/tests` passed (7 tests as part of the combined 35-test module run); `node --import tsx modules/media/examples/demo.ts` completed without credentials. Exported-project verification: passed 2026-10-09 in the standalone full recipe (clean npm ci, types, module tests, production build and local HTTP). Live vision: **not run**; requires authorized test credentials. Camera hardware and real video decoding are not exercised by Node contract tests; verify target browser/codec combinations with representative videos before shipping.

## 8. What does it depend on, and what are its limits?

Zod, React and shared runtime/contracts. Resize cap is configurable up to 4096 pixels on the longest edge, input/encoded image limit defaults to 8 MB, decoded-image cap is 40 megapixels; frame sampling defaults to 120 seconds and can be explicitly configured up to 600 seconds. Longest video limit remains 50 MB and 12 frames. Sampling can miss short events. Model localization is approximate; confidence is uncalibrated and not a safety signal. This is not an object-tracking, face-identification or full-video model pipeline. No API calls in local mode; live costs depend on the chosen model and image count.

Official formats checked: [OpenAI image input](https://developers.openai.com/api/docs/guides/images-vision). Browser permission reference: [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia). Original implementation and authored SVG/JSON fixtures: MIT.
