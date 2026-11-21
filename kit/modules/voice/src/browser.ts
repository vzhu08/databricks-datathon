export type RecorderStatus =
  'idle' | 'requesting' | 'recording' | 'ready' | 'denied' | 'unsupported' | 'error';
export type RecorderSnapshot = { status: RecorderStatus; message?: string; blob?: Blob };
/** One recorder per component. Cancellation invalidates pending permission prompts and releases late streams. */
export class MicrophoneRecorder {
  private stream?: MediaStream;
  private recorder?: MediaRecorder;
  private timer?: ReturnType<typeof setTimeout>;
  private generation = 0;
  private active = false;
  constructor(
    private notify: (snapshot: RecorderSnapshot) => void,
    private maxSeconds = 60,
    private maxBytes = 10_000_000,
  ) {
    if (
      !Number.isFinite(maxSeconds) ||
      maxSeconds < 1 ||
      maxSeconds > 300 ||
      !Number.isInteger(maxBytes) ||
      maxBytes < 1 ||
      maxBytes > 20_000_000
    )
      throw new Error('Invalid recording limits');
  }
  async start() {
    if (this.active) return;
    if (!globalThis.navigator?.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      this.notify({
        status: 'unsupported',
        message: 'Microphone recording requires HTTPS/localhost and MediaRecorder support.',
      });
      return;
    }
    this.active = true;
    const generation = ++this.generation;
    this.notify({ status: 'requesting' });
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (generation !== this.generation) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      this.recorder = recorder;
      const chunks: Blob[] = [];
      let bytes = 0;
      let failure: string | undefined;
      recorder.ondataavailable = (event) => {
        if (generation !== this.generation) return;
        bytes += event.data.size;
        if (bytes > this.maxBytes) {
          failure = 'Recording exceeded byte limit. Try a shorter recording.';
          this.stop();
        } else if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (generation !== this.generation) return;
        failure = 'The browser could not record audio.';
        this.stop();
      };
      recorder.onstop = () => {
        if (generation !== this.generation) return;
        this.release();
        const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' });
        this.notify(
          failure || !blob.size
            ? { status: 'error', message: failure ?? 'No audio was captured.' }
            : { status: 'ready', blob },
        );
      };
      recorder.start(250);
      this.timer = setTimeout(() => this.stop(), this.maxSeconds * 1000);
      this.notify({ status: 'recording' });
    } catch (error) {
      if (generation !== this.generation) return;
      this.release();
      const denied =
        error instanceof DOMException && ['NotAllowedError', 'SecurityError'].includes(error.name);
      this.notify({
        status: denied ? 'denied' : 'error',
        message: denied
          ? 'Microphone permission denied. Enable it in your browser site settings, then retry.'
          : 'Unable to open microphone. Check that a microphone is available.',
      });
    }
  }
  stop() {
    if (this.recorder?.state === 'recording') this.recorder.stop();
  }
  cancel() {
    ++this.generation;
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    this.release();
    this.notify({ status: 'idle' });
  }
  dispose() {
    ++this.generation;
    if (this.recorder && this.recorder.state !== 'inactive') this.recorder.stop();
    this.release();
  }
  private release() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
    this.recorder = undefined;
    this.active = false;
  }
}
