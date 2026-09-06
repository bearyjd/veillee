/* Photographs.
 *
 * Deliberately plainer than the recorder: a file input, a caption box, and a
 * save button. The caption is the part that matters - in fifty years the
 * picture will still be there and the only person who knew who was in it will
 * not be - so it is editable at any time, not only at upload.
 */
window.veilleePhotos = function (questionId) {
  "use strict";

  return {
    uploading: false,
    error: "",
    pendingDelete: "",
    deleteWord: "",

    uploadPhoto: async function () {
      var input = document.getElementById("photo-file");
      if (!input || !input.files || input.files.length === 0) {
        this.error = "Choose a photograph first.";
        return;
      }
      this.error = "";
      this.uploading = true;

      var payload = new FormData();
      payload.append("file", input.files[0]);
      var caption = document.getElementById("photo-caption");
      payload.append("caption", caption ? caption.value : "");

      try {
        var response = await fetch("/api/photo/" + encodeURIComponent(questionId), {
          method: "POST",
          body: payload,
        });
        if (!response.ok) {
          var detail = await response.json().catch(function () {
            return {};
          });
          throw new Error(detail.detail || "that picture could not be saved");
        }
        window.location.reload();
      } catch (err) {
        this.error = "Couldn't save that photograph: " + err.message;
      } finally {
        this.uploading = false;
      }
    },

    saveCaption: async function (event, photoId) {
      var form = event.target;
      var body = new FormData(form);
      var button = form.querySelector("button[type=submit]");
      try {
        var response = await fetch("/api/photo/" + encodeURIComponent(photoId) + "/caption", {
          method: "POST",
          body: body,
        });
        if (!response.ok) throw new Error("it was not saved");
        if (button) {
          button.textContent = "Saved";
          window.setTimeout(function () {
            button.textContent = "Save this description";
          }, 2000);
        }
      } catch (err) {
        this.error = "Couldn't save that description: " + err.message;
      }
    },

    askDelete: function (photoId) {
      this.pendingDelete = photoId;
      this.deleteWord = "";
      this.$nextTick(function () {
        var field = document.getElementById("photo-delete-word");
        if (field) field.focus();
      });
    },

    cancelDelete: function () {
      this.pendingDelete = "";
      this.deleteWord = "";
    },

    doDelete: async function () {
      if (this.deleteWord.trim().toLowerCase() !== "delete") return;
      try {
        var response = await fetch(
          "/api/photo/" + encodeURIComponent(this.pendingDelete) + "/delete",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm: this.deleteWord.trim().toLowerCase() }),
          }
        );
        if (!response.ok) throw new Error("it was not removed");
        window.location.reload();
      } catch (err) {
        this.error = err.message;
      }
    },
  };
};
