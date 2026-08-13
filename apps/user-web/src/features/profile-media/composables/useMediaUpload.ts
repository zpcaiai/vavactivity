import { ref } from "vue";

import { profileMediaApiClient } from "@/features/profile-media/api";
import type { MediaKind, ProfileMediaView, UploadTarget } from "@/features/profile-media/types";

/**
 * Register → upload bytes → finalize.
 *
 * The bytes go straight to object storage and never through the API. The server
 * hands back a signed POST policy whose fields must be sent verbatim, with the
 * file appended last: an S3 POST policy ignores anything after the file part,
 * and rejects any field the signature does not cover. That is the point — the
 * size and type ceiling lives in that signature rather than in this file, so it
 * cannot be edited away from the client.
 */
export function useMediaUpload() {
  const uploading = ref(false);
  const progressPercent = ref(0);
  const error = ref<string | null>(null);
  const errorCode = ref<string | null>(null);

  function reset() {
    error.value = null;
    errorCode.value = null;
    progressPercent.value = 0;
  }

  /** Duration is only knowable for video, and only by decoding it locally. */
  async function probeDuration(file: File): Promise<number | null> {
    if (!file.type.startsWith("video/")) return null;
    return new Promise((resolve) => {
      const element = document.createElement("video");
      element.preload = "metadata";
      element.onloadedmetadata = () => {
        URL.revokeObjectURL(element.src);
        resolve(Number.isFinite(element.duration) ? Math.round(element.duration) : null);
      };
      // A file whose duration cannot be read is not quietly sent as 0. The
      // server rejects a video with no duration, which is the honest outcome
      // for a file this browser could not decode.
      element.onerror = () => {
        URL.revokeObjectURL(element.src);
        resolve(null);
      };
      element.src = URL.createObjectURL(file);
    });
  }

  function postToStorage(target: UploadTarget["upload"], file: File): Promise<void> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      for (const [key, value] of Object.entries(target.fields)) {
        form.append(key, String(value));
      }
      form.append("file", file);

      // XHR rather than fetch: this is the one place a progress bar is worth
      // having, because a 100 MB video on a phone is a minute of silence
      // otherwise.
      const request = new XMLHttpRequest();
      request.open(target.method, target.url, true);
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          progressPercent.value = Math.round((event.loaded / event.total) * 100);
        }
      };
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) resolve();
        else reject(new Error(`storage rejected the upload (${request.status})`));
      };
      request.onerror = () => reject(new Error("the upload could not reach storage"));
      request.send(form);
    });
  }

  async function upload(file: File, kind: MediaKind): Promise<ProfileMediaView | null> {
    reset();
    uploading.value = true;
    try {
      const duration = await probeDuration(file);
      const registered = await profileMediaApiClient.registerUpload({
        kind,
        mime_type: file.type,
        byte_size: file.size,
        duration_seconds: duration
      });

      await postToStorage(registered.upload, file);

      // Finalize measures the object from storage rather than trusting these
      // numbers, so a mismatch surfaces here instead of becoming an asset.
      return await profileMediaApiClient.finalize(registered.asset_id, {
        byte_size: file.size,
        mime_type: file.type,
        duration_seconds: duration
      });
    } catch (caught) {
      error.value = (caught as Error).message;
      errorCode.value = (caught as Error & { code?: string }).code ?? null;
      return null;
    } finally {
      uploading.value = false;
    }
  }

  return { uploading, progressPercent, error, errorCode, upload, reset };
}
