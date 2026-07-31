import { createI18n } from "vue-i18n";

import enExtensions from "./locales/en.json";
import zhCNExtensions from "./locales/zh-CN.json";
import zhTWExtensions from "./locales/zh-TW.json";

export const supportedLocales = ["zh-CN", "zh-TW", "en"] as const;
export type SupportedLocale = (typeof supportedLocales)[number];

const messages = {
  "zh-CN": {
    ...zhCNExtensions,
    brand: { promise: "认真认识，安心同行" },
    nav: {
      home: "首页",
      about: "关于 VAV",
      stories: "幸福见证",
      articles: "文章",
      activities: "活动",
      courses: "课程",
      counseling: "真人辅导",
      ai: "AI 辅导",
      account: "我的账户",
      menu: "打开导航"
    },
    home: {
      eyebrow: "有边界的认识 · 有支持的成长",
      title: "让重要的关系，开始得更从容。",
      intro:
        "VAV 把可信活动、成长课程与专业辅导放进同一条清晰路径。你可以按自己的节奏了解、参与和决定。",
      explore: "探索服务",
      learn: "了解我们的原则",
      trustTitle: "每一步都应当清楚、可撤回、被尊重",
      trustBody:
        "平台不会以 AI 替你做关系决定。身份、支付、权限与安全处置由明确的服务规则保护。",
      steps: {
        discover: "先了解",
        discoverBody: "阅读内容与服务说明，不必先交出私人资料。",
        grow: "再成长",
        growBody: "通过活动、课程或辅导整理期待与边界。",
        connect: "后认识",
        connectBody: "匹配能力将在审核、隐私和双方选择机制完备后开放。"
      }
    },
    pages: {
      about: {
        eyebrow: "关于 VAV",
        title: "关系服务，首先是一份信任责任。",
        body: "我们以尊重、知情选择和可解释规则设计每一项服务。正式业务政策仍由负责人确认并公开。"
      },
      stories: {
        eyebrow: "幸福见证",
        title: "真实故事需要真实授权。",
        body: "见证内容功能已就绪；在获得当事人明确授权和隐私审查前，我们不会展示虚构案例。"
      },
      articles: {
        eyebrow: "文章",
        title: "把复杂的关系问题，说得清楚而温和。",
        body: "内容中心将承载婚恋成长、沟通边界与信仰生活文章，并保留作者、版本和引用来源。"
      },
      activities: {
        eyebrow: "活动中心",
        title: "在线下相遇前，先知道会发生什么。",
        body: "活动发布、报名、审核、支付、签到和分组将在后续批次形成完整闭环。"
      },
      courses: {
        eyebrow: "成长课程",
        title: "学习不是通往配对的门槛。",
        body: "课程将支持章节、视频、练习与进度记录，并把购买权限与学习内容清楚分开。"
      },
      counseling: {
        eyebrow: "真人辅导",
        title: "需要被听见时，转向真实的人。",
        body: "导师资料、预约时间、确认方式和隐私边界会在上线前清楚展示；排班模式仍待业务确认。"
      },
      ai: {
        eyebrow: "哈拿老师 AI 辅导",
        title: "AI 可以帮助梳理，但不替你判断人生。",
        body: "AI 服务当前尚未开放。未来回答会标注来源、识别风险，并在高风险情况下停止一般建议、转介真人支持。"
      }
    },
    auth: {
      loginTitle: "欢迎回来",
      registerTitle: "建立 VAV 账户",
      unavailable:
        "账户能力将在身份认证批次完成后开放。当前页面只展示正式入口，不收集或保存任何资料。",
      returnHome: "返回首页"
    },
    account: {
      title: "我的账户",
      signedOut: "你当前尚未登录。注册、隐私设置与数据权利将在账户模块完成后在这里提供。",
      login: "前往登录"
    },
    common: { coming: "正在建立可靠的服务闭环", language: "语言", close: "关闭" }
  },
  "zh-TW": {
    ...zhTWExtensions,
    brand: { promise: "認真認識，安心同行" },
    nav: {
      home: "首頁",
      about: "關於 VAV",
      stories: "幸福見證",
      articles: "文章",
      activities: "活動",
      courses: "課程",
      counseling: "真人輔導",
      ai: "AI 輔導",
      account: "我的帳戶",
      menu: "開啟導覽"
    },
    home: {
      eyebrow: "有邊界的認識 · 有支持的成長",
      title: "讓重要的關係，開始得更從容。",
      intro: "VAV 把可信活動、成長課程與專業輔導放在同一條清楚路徑。你可以按自己的節奏了解、參與和決定。",
      explore: "探索服務",
      learn: "了解我們的原則",
      trustTitle: "每一步都應當清楚、可撤回、被尊重",
      trustBody: "平台不會以 AI 替你做關係決定。身份、付款、權限與安全處置由明確的服務規則保護。",
      steps: {
        discover: "先了解",
        discoverBody: "閱讀內容與服務說明，不必先交出私人資料。",
        grow: "再成長",
        growBody: "透過活動、課程或輔導整理期待與邊界。",
        connect: "後認識",
        connectBody: "配對能力會在審核、隱私和雙方選擇機制完備後開放。"
      }
    },
    pages: {
      about: { eyebrow: "關於 VAV", title: "關係服務，首先是一份信任責任。", body: "我們以尊重、知情選擇和可解釋規則設計每一項服務。正式業務政策仍由負責人確認並公開。" },
      stories: { eyebrow: "幸福見證", title: "真實故事需要真實授權。", body: "見證內容功能已就緒；在取得當事人明確授權和隱私審查前，我們不會展示虛構案例。" },
      articles: { eyebrow: "文章", title: "把複雜的關係問題，說得清楚而溫和。", body: "內容中心將承載婚戀成長、溝通邊界與信仰生活文章，並保留作者、版本和引用來源。" },
      activities: { eyebrow: "活動中心", title: "在線下相遇前，先知道會發生什麼。", body: "活動發布、報名、審核、付款、簽到和分組會在後續批次形成完整閉環。" },
      courses: { eyebrow: "成長課程", title: "學習不是通往配對的門檻。", body: "課程將支援章節、影片、練習與進度記錄，並把購買權限與學習內容清楚分開。" },
      counseling: { eyebrow: "真人輔導", title: "需要被聽見時，轉向真實的人。", body: "導師資料、預約時間、確認方式和隱私邊界會在上線前清楚展示；排班模式仍待業務確認。" },
      ai: { eyebrow: "哈拿老師 AI 輔導", title: "AI 可以幫助梳理，但不替你判斷人生。", body: "AI 服務目前尚未開放。未來回答會標註來源、識別風險，並在高風險情況下停止一般建議、轉介真人支持。" }
    },
    auth: { loginTitle: "歡迎回來", registerTitle: "建立 VAV 帳戶", unavailable: "帳戶能力會在身份認證批次完成後開放。目前頁面只展示正式入口，不收集或保存任何資料。", returnHome: "返回首頁" },
    account: { title: "我的帳戶", signedOut: "你目前尚未登入。註冊、隱私設定與資料權利會在帳戶模組完成後提供。", login: "前往登入" },
    common: { coming: "正在建立可靠的服務閉環", language: "語言", close: "關閉" }
  },
  en: {
    ...enExtensions,
    brand: { promise: "Meet thoughtfully. Walk forward safely." },
    nav: {
      home: "Home",
      about: "About VAV",
      stories: "Stories",
      articles: "Articles",
      activities: "Activities",
      courses: "Courses",
      counseling: "Counseling",
      ai: "AI guidance",
      account: "My account",
      menu: "Open navigation"
    },
    home: {
      eyebrow: "Clear boundaries · Supported growth",
      title: "Let important relationships begin with room to breathe.",
      intro: "VAV brings trusted activities, growth courses and professional guidance into one clear path. Learn, participate and decide at your own pace.",
      explore: "Explore services",
      learn: "Read our principles",
      trustTitle: "Every step should be clear, reversible and respected",
      trustBody: "AI will not make relationship decisions for you. Identity, payments, permissions and safety actions remain governed by explicit service rules.",
      steps: {
        discover: "Understand first",
        discoverBody: "Read about services without surrendering private information.",
        grow: "Grow next",
        growBody: "Use activities, courses or counseling to clarify hopes and boundaries.",
        connect: "Connect later",
        connectBody: "Matchmaking opens only after review, privacy and mutual-choice safeguards are complete."
      }
    },
    pages: {
      about: { eyebrow: "About VAV", title: "A relationship service begins with a duty of trust.", body: "We design for respect, informed choice and explainable rules. Accountable owners must confirm and publish formal business policy." },
      stories: { eyebrow: "Stories", title: "Real stories require real consent.", body: "The publishing surface is ready. No invented testimonials will appear while explicit consent and privacy review are pending." },
      articles: { eyebrow: "Articles", title: "Clear, gentle language for complex relationship questions.", body: "The content center will preserve authorship, versions and sources across relationship growth, communication boundaries and faith." },
      activities: { eyebrow: "Activities", title: "Know what will happen before meeting in person.", body: "Publishing, registration, review, payment, check-in and grouping arrive as a complete workflow in a later batch." },
      courses: { eyebrow: "Growth courses", title: "Learning is not a gate you must pass to be matched.", body: "Courses will track chapters, media, exercises and progress while keeping purchase access separate from learning records." },
      counseling: { eyebrow: "Human counseling", title: "When you need to be heard, turn toward a real person.", body: "Mentor credentials, appointment timing and privacy boundaries will be visible before launch. Scheduling policy is still undecided." },
      ai: { eyebrow: "Hannah AI guidance", title: "AI may help you reflect. It does not decide your life.", body: "AI guidance is currently unavailable. Future answers will show sources, recognize risk and hand high-risk situations to human support." }
    },
    auth: { loginTitle: "Welcome back", registerTitle: "Create a VAV account", unavailable: "Account features open after the identity batch. This page is an entry point only and does not collect or store information.", returnHome: "Return home" },
    account: { title: "My account", signedOut: "You are not signed in. Registration, privacy controls and data rights will appear here after the account module is complete.", login: "Go to sign in" },
    common: { coming: "Building a dependable service journey", language: "Language", close: "Close" }
  }
} as const;

export const i18n = createI18n({
  legacy: false,
  locale: "zh-CN",
  fallbackLocale: "en",
  messages
});
