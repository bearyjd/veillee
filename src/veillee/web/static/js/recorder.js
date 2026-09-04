/* Recording, both ways.
 *
 * Path A uploads chunks while he is still talking, so a dead battery or a
 * closed lid costs a few seconds rather than an hour. Path B is the file input
 * in the template and needs almost no JavaScript at all, which is exactly why
 * it is there: it is the path that still works when this file's assumptions
 * about the browser turn out to be wrong.
 */
window.veilleeRecorder = function (questionId) {
  "use strict";

  var CHUNK_MS = 3000;

  return {
    supported: false,
    recording: false,
    paused: false,
    uploading: false,
    elapsed: 0,
    level: 0,
    error: "",
    done: false,

    // Not reactive state; just handles we need to hang on to.
    _recorder: null,
    _stream: null,
    _audioContext: null,
    _uploadId: null,
    _chunkIndex: 0,
    _pending: [],
    _timer: null,
    _meter: null,

    init: function () {
      this.supported =
        typeof MediaRecorder !== "undefined" &&
        !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    },

    get clock() {
      var total = Math.floor(this.elapsed);
      var minutes = Math.floor(total / 60);
      var seconds = total % 60;
      return minutes + ":" + String(seconds).padStart(2, "0");
    },

    toggle: function () {
      return this.recording ? this.stop() : this.start();
    },

    start: async function () {
      this.error = "";
      this.done = false;
      try {
        this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        this.error =
          "This browser wouldn't give the page a microphone. " +
          "Use the upload below instead — it works just as well.";
        return;
      }

      try {
        var started = await fetch("/api/recording/" + encodeURIComponent(questionId) + "/start", {
          method: "POST",
        });
        if (!started.ok) throw new Error("could not open a recording session");
        this._uploadId = (await started.json()).upload_id;
      } catch (err) {
        this.error = "Couldn't start recording. Please try the upload below.";
        this._release();
        return;
      }

      this._chunkIndex = 0;
      this._pending = [];
      this.elapsed = 0;

      this._recorder = new MediaRecorder(this._stream, this._pickFormat());
      this._recorder.ondataavailable = this._onChunk.bind(this);
      this._recorder.onerror = function () {
        this.error = "The recording stopped unexpectedly. Whatever arrived has been kept.";
      }.bind(this);
      this._recorder.start(CHUNK_MS);

      this.recording = true;
      this.paused = false;
      this._startMeter();
      this._timer = window.setInterval(
        function () {
          if (!this.paused) this.elapsed += 1;
        }.bind(this),
        1000
      );
    },

    /* Pause and resume, so he can stop for a cup of tea or to find a name
       without ending the recording and starting a second file. */
    togglePause: function () {
      if (!this._recorder) return;
      if (this.paused) {
        this._recorder.resume();
        this.paused = false;
        this._startMeter();
      } else {
        this._recorder.pause();
        this.paused = true;
        this.level = 0;
      }
    },

    _pickFormat: function () {
      var candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
      for (var i = 0; i < candidates.length; i++) {
        if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(candidates[i])) {
          return { mimeType: candidates[i] };
        }
      }
      return {};
    },

    /* Every chunk goes to disk on the server the moment it exists. */
    _onChunk: function (event) {
      if (!event.data || event.data.size === 0 || !this._uploadId) return;
      var index = this._chunkIndex++;
      var request = fetch(
        "/api/recording/" + encodeURIComponent(this._uploadId) + "/chunk?index=" + index,
        { method: "POST", body: event.data }
      ).catch(
        function () {
          // Report but keep recording: losing one chunk is far better than
          // stopping him mid-sentence.
          this.error = "Some audio didn't reach the server. The rest is still being saved.";
        }.bind(this)
      );
      this._pending.push(request);
    },

    stop: async function () {
      if (!this._recorder) return;
      var recorder = this._recorder;
      var finished = new Promise(function (resolve) {
        recorder.onstop = resolve;
      });
      recorder.stop();
      await finished;

      this.recording = false;
      this.paused = false;
      this._release();
      await Promise.all(this._pending);

      this.uploading = true;
      try {
        var response = await fetch(
          "/api/recording/" + encodeURIComponent(this._uploadId) + "/finish",
          { method: "POST" }
        );
        if (!response.ok) {
          var detail = await response.json().catch(function () {
            return {};
          });
          throw new Error(detail.detail || "the recording could not be saved");
        }
        this.done = true;
        window.setTimeout(function () {
          window.location.reload();
        }, 900);
      } catch (err) {
        this.error = "Couldn't finish saving: " + err.message + " Please try the upload below.";
      } finally {
        this.uploading = false;
        this._uploadId = null;
      }
    },

    _startMeter: function () {
      try {
        var Context = window.AudioContext || window.webkitAudioContext;
        this._audioContext = new Context();
        var source = this._audioContext.createMediaStreamSource(this._stream);
        var analyser = this._audioContext.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        var data = new Uint8Array(analyser.frequencyBinCount);
        var tick = function () {
          if (!this.recording || this.paused) return;
          analyser.getByteTimeDomainData(data);
          var peak = 0;
          for (var i = 0; i < data.length; i++) {
            peak = Math.max(peak, Math.abs(data[i] - 128));
          }
          this.level = Math.min(100, Math.round((peak / 128) * 220));
          this._meter = window.requestAnimationFrame(tick);
        }.bind(this);
        tick();
      } catch (err) {
        // A missing level meter is cosmetic; recording continues regardless.
        this.level = 0;
      }
    },

    _release: function () {
      if (this._timer) window.clearInterval(this._timer);
      if (this._meter) window.cancelAnimationFrame(this._meter);
      this._timer = null;
      this._meter = null;
      if (this._stream) {
        this._stream.getTracks().forEach(function (track) {
          track.stop();
        });
        this._stream = null;
      }
      if (this._audioContext) {
        this._audioContext.close().catch(function () {});
        this._audioContext = null;
      }
      this._recorder = null;
      this.level = 0;
    },

    /* Path B: a file recorded somewhere else entirely. */
    uploadFile: async function (event) {
      var input = document.getElementById("audio-file");
      if (!input || !input.files || input.files.length === 0) {
        this.error = "Choose a recording first.";
        return;
      }
      this.error = "";
      this.uploading = true;

      var payload = new FormData();
      payload.append("file", input.files[0]);
      payload.append("device", navigator.userAgent);

      try {
        var response = await fetch("/api/upload/" + encodeURIComponent(questionId), {
          method: "POST",
          body: payload,
        });
        if (!response.ok) {
          var detail = await response.json().catch(function () {
            return {};
          });
          throw new Error(detail.detail || "that file could not be saved");
        }
        this.done = true;
        window.setTimeout(function () {
          window.location.reload();
        }, 900);
      } catch (err) {
        this.error = "Couldn't save that recording: " + err.message;
      } finally {
        this.uploading = false;
      }
    },

    confirmDelete: async function (recordingId) {
      var typed = window.prompt(
        "This removes the recording from the page. Type the word delete to confirm."
      );
      if (typed === null) return;
      try {
        var response = await fetch(
          "/api/recording/" + encodeURIComponent(recordingId) + "/delete",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm: typed }),
          }
        );
        if (!response.ok) {
          var detail = await response.json().catch(function () {
            return {};
          });
          throw new Error(detail.detail || "it was not removed");
        }
        window.location.reload();
      } catch (err) {
        this.error = err.message;
      }
    },
  };
};
