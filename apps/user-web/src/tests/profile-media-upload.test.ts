import { beforeEach, describe, expect, it, vi } from "vitest";

const bootstrap = vi.fn(async () => undefined);
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ bootstrap, accessToken: "member-token", user: { id: "member" } })
}));

import { useMediaUpload } from "@/features/profile-media/composables/useMediaUpload";

interface SentUpload {
  url: string;
  method: string;
  fieldOrder: string[];
  fields: Record<string, string>;
}

const sent: SentUpload[] = [];

/**
 * Minimal XMLHttpRequest stand-in. The upload path uses XHR rather than fetch
 * because it needs progress events, so the test has to speak the same shape.
 */
class FakeXhr {
  public upload = { onprogress: null as ((event: ProgressEvent) => void) | null };
  public onload: (() => void) | null = null;
  public onerror: (() => void) | null = null;
  public status = 204;
  private url = "";
  private method = "";

  static failNext = false;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body: FormData) {
    const fieldOrder = [...body.keys()];
    const fields: Record<string, string> = {};
    for (const [key, value] of body.entries()) {
      if (typeof value === "string") fields[key] = value;
    }
    sent.push({ url: this.url, method: this.method, fieldOrder, fields });
    if (FakeXhr.failNext) {
      FakeXhr.failNext = false;
      this.status = 403;
    }
    this.onload?.();
  }
}

const policy = {
  url: "https://storage.example/vav-private",
  method: "POST" as const,
  fields: { key: "profile-media/TOKEN", "Content-Type": "image/png", policy: "b64", signature: "s" },
  max_bytes: 10 * 1024 * 1024,
  expires_in_seconds: 900
};

function stubApi(overrides: { finalizeFails?: boolean } = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/uploads")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            data: {
              asset_id: "asset-1",
              upload_path: "/media/private/TOKEN",
              upload: policy,
              state: "uploading",
              moderation_state: "pending"
            }
          })
        };
      }
      if (url.includes("/finalize")) {
        if (overrides.finalizeFails) {
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: { message: "no bytes", code: "MEDIA_BYTES_MISSING" } })
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            data: {
              assets: [],
              pending_assets: [],
              mbti: null,
              intro: null,
              city_code: null,
              completeness_percent: 40,
              completeness_missing: [],
              is_published: false
            }
          })
        };
      }
      return { ok: true, status: 200, json: async () => ({ data: {} }) };
    })
  );
}

function pngFile(size = 2048): File {
  return new File([new Uint8Array(size)], "photo.png", { type: "image/png" });
}

describe("profile media upload", () => {
  beforeEach(() => {
    sent.length = 0;
    FakeXhr.failNext = false;
    vi.unstubAllGlobals();
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

  it("sends the bytes to storage, not to the API", async () => {
    stubApi();
    const uploader = useMediaUpload();

    await uploader.upload(pngFile(), "photo");

    expect(sent).toHaveLength(1);
    // The whole point of the presigned policy: object bytes never traverse the
    // API, which is this platform's stated convention.
    expect(sent[0]?.url).toBe(policy.url);
    expect(sent[0]?.method).toBe("POST");
  });

  it("sends the policy fields verbatim with the file last", async () => {
    stubApi();
    const uploader = useMediaUpload();

    await uploader.upload(pngFile(), "photo");

    const order = sent[0]?.fieldOrder ?? [];
    // S3 ignores anything after the file part, so a file appended early would
    // silently drop the signature fields and the upload would be rejected.
    expect(order[order.length - 1]).toBe("file");
    expect(sent[0]?.fields.key).toBe(policy.fields.key);
    expect(sent[0]?.fields.policy).toBe(policy.fields.policy);
    expect(sent[0]?.fields.signature).toBe(policy.fields.signature);
  });

  it("does not finalize when storage rejects the upload", async () => {
    stubApi();
    FakeXhr.failNext = true;
    const uploader = useMediaUpload();

    const result = await uploader.upload(pngFile(), "photo");

    expect(result).toBeNull();
    expect(uploader.error.value).toContain("403");
    const finalizeCalls = (fetch as unknown as { mock: { calls: [string][] } }).mock.calls.filter(
      ([url]) => String(url).includes("/finalize")
    );
    // Finalizing after a failed upload would create an active asset backed by
    // nothing — a broken image occupying one of three photo slots.
    expect(finalizeCalls).toHaveLength(0);
  });

  it("surfaces the server's code when finalize refuses", async () => {
    stubApi({ finalizeFails: true });
    const uploader = useMediaUpload();

    const result = await uploader.upload(pngFile(), "photo");

    expect(result).toBeNull();
    expect(uploader.errorCode.value).toBe("MEDIA_BYTES_MISSING");
  });

  it("clears its error state between attempts", async () => {
    stubApi();
    FakeXhr.failNext = true;
    const uploader = useMediaUpload();
    await uploader.upload(pngFile(), "photo");
    expect(uploader.error.value).not.toBeNull();

    await uploader.upload(pngFile(), "photo");

    expect(uploader.error.value).toBeNull();
  });
});
