import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  media: vi.fn(),
  remove: vi.fn(),
  shareConsent: vi.fn(),
  setShareConsent: vi.fn(),
  setTags: vi.fn()
}));
const uploadMocks = vi.hoisted(() => ({ upload: vi.fn() }));
const grantMocks = vi.hoisted(() => ({
  loadMediaGrants: vi.fn(),
  refreshAfterMediaError: vi.fn()
}));

vi.mock("@/features/profile-media/api", () => ({ profileMediaApiClient: apiMocks }));
vi.mock("@/features/profile-media/composables/useMediaUpload", async () => {
  const { ref } = await import("vue");
  return {
    useMediaUpload: () => ({
      uploading: ref(false),
      progressPercent: ref(0),
      error: ref<string | null>(null),
      upload: uploadMocks.upload
    })
  };
});
vi.mock("@/features/profile-media/composables/useMediaGrants", async () => {
  const { ref } = await import("vue");
  return {
    useMediaGrants: () => ({
      mediaUrls: ref({
        "old-asset": "https://storage.example/old",
        "old-video": "https://storage.example/video",
        "replacement-asset": "https://storage.example/replacement"
      }),
      loadMediaGrants: grantMocks.loadMediaGrants,
      refreshAfterMediaError: grantMocks.refreshAfterMediaError
    })
  };
});
vi.mock("vue-i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
    te: () => false
  })
}));

import ProfileMediaPage from "@/features/profile-media/pages/ProfileMediaPage.vue";
import type {
  MediaAsset,
  MediaKind,
  ProfileMediaView
} from "@/features/profile-media/types";

function asset(assetId: string, kind: MediaKind = "photo"): MediaAsset {
  return {
    asset_id: assetId,
    kind,
    state: "active",
    moderation_state: "approved",
    rejection_reason_code: null,
    position: kind === "photo" ? 1 : null,
    duration_seconds: kind === "video" ? 12.5 : null,
    media_path: `/media/private/${assetId}`,
    is_publishable: true
  };
}

function mediaView(assets: MediaAsset[]): ProfileMediaView {
  return {
    assets,
    pending_assets: [],
    mbti: null,
    intro: null,
    city_code: null,
    completeness_percent: assets.length ? 100 : 0,
    completeness_missing: [],
    is_published: assets.length > 0
  };
}

function mountPage() {
  return mount(ProfileMediaPage, {
    global: {
      stubs: {
        UserPageLayout: { template: "<main><slot /></main>" },
        VAlert: { template: "<aside><slot /></aside>" },
        VCard: { template: "<section><slot /></section>" },
        VChip: { template: "<span />" },
        VPageState: { template: "<div />" },
        VButton: {
          props: ["disabled"],
          emits: ["click"],
          template:
            '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>'
        }
      }
    }
  });
}

let wrapper: VueWrapper | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.shareConsent.mockResolvedValue({
    share_enabled: false,
    share_photos: false,
    share_video: false,
    share_mbti: false,
    share_intro: false,
    share_city: false
  });
  grantMocks.loadMediaGrants.mockResolvedValue(undefined);
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

describe("profile media page mutations", () => {
  it("reloads the media projection and grants after DELETE returns deletion metadata", async () => {
    apiMocks.media
      .mockResolvedValueOnce(mediaView([asset("old-asset")]))
      .mockResolvedValueOnce(mediaView([]));
    apiMocks.remove.mockResolvedValue({
      asset_id: "old-asset",
      remaining_photos: 0,
      profile_falls_below_minimum: true
    });
    wrapper = mountPage();
    await flushPromises();

    expect(wrapper.get('[data-testid="profile-media-old-asset"]').attributes("src")).toBe(
      "https://storage.example/old"
    );
    const remove = wrapper.findAll("button").find((button) => button.text() === "profileMedia.remove");
    expect(remove).toBeDefined();
    await remove?.trigger("click");
    await flushPromises();

    expect(apiMocks.remove).toHaveBeenCalledWith("old-asset");
    expect(apiMocks.media).toHaveBeenCalledTimes(2);
    expect(grantMocks.loadMediaGrants).toHaveBeenLastCalledWith([]);
    expect(wrapper.find('[data-testid="profile-media-old-asset"]').exists()).toBe(false);
  });

  it("offers photo and video replacement while retaining the old asset until finalize", async () => {
    const current = mediaView([asset("old-asset"), asset("old-video", "video")]);
    const replacement = mediaView([asset("replacement-asset"), asset("old-video", "video")]);
    apiMocks.media.mockResolvedValue(current);
    let finishUpload!: (view: ProfileMediaView | null) => void;
    uploadMocks.upload.mockReturnValue(
      new Promise<ProfileMediaView | null>((resolve) => {
        finishUpload = resolve;
      })
    );
    wrapper = mountPage();
    await flushPromises();

    expect(wrapper.find('[data-testid="replace-video"]').exists()).toBe(true);
    const input = wrapper.get<HTMLInputElement>('[data-testid="replace-photo-old-asset"]');
    const file = new File([new Uint8Array(2048)], "replacement.png", { type: "image/png" });
    Object.defineProperty(input.element, "files", { configurable: true, value: [file] });
    await input.trigger("change");

    expect(uploadMocks.upload).toHaveBeenCalledWith(file, "photo", "old-asset");
    expect(wrapper.find('[data-testid="profile-media-old-asset"]').exists()).toBe(true);

    finishUpload(replacement);
    await flushPromises();

    expect(wrapper.find('[data-testid="profile-media-old-asset"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="profile-media-replacement-asset"]').attributes("src")).toBe(
      "https://storage.example/replacement"
    );
    expect(grantMocks.loadMediaGrants).toHaveBeenLastCalledWith(replacement.assets);
    expect(wrapper.text()).toContain("profileMedia.replaceDone");
  });
});
