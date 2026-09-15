import type { CreateVideoBody } from "../api";

export type Aspect = "16:9" | "9:16" | "1:1";

export interface WizardState {
  /** Where the narration comes from. Offline is a first-class choice, not a
   *  fallback: the video is real either way, only the words differ. */
  engine: "offline" | "api";
  baseUrl: string;
  model: string;
  apiKey: string;

  topic: string;
  duration: number;
  aspect: Aspect;
  language: string;
  scenes: number | null;
  captions: boolean;

  presetId: string | null;
  notes: string;

  /** ``null`` means "let the ranker choose", which is the default and is a
   *  different statement from picking a template that happens to be common. */
  templateId: string | null;
  styleId: string | null;
}

export const ASPECTS: {
  id: Aspect;
  label: string;
  where: string;
  platform: string;
}[] = [
  {
    id: "16:9",
    label: "横屏 16:9",
    where: "B站、YouTube、公众号、投屏",
    platform: "bilibili_16x9",
  },
  {
    id: "9:16",
    label: "竖屏 9:16",
    where: "抖音、视频号、小红书、Shorts",
    platform: "tiktok_9x16",
  },
  {
    id: "1:1",
    label: "方形 1:1",
    where: "朋友圈、信息流广告",
    platform: "square_1x1",
  },
];

export const DURATIONS = [30, 60, 90, 120];

export const LANGUAGES: { id: string; label: string }[] = [
  { id: "zh-CN", label: "中文（简体）" },
  { id: "en-US", label: "English" },
];

/** A few well-known endpoints, so nobody has to memorise a base URL. */
export const LLM_PRESETS: {
  id: string;
  name: string;
  baseUrl: string;
  model: string;
  hint: string;
}[] = [
  {
    id: "deepseek",
    name: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    hint: "国内直连，价格低，中文写作好",
  },
  {
    id: "openai",
    name: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    hint: "需要能访问 api.openai.com",
  },
  {
    id: "moonshot",
    name: "月之暗面 Kimi",
    baseUrl: "https://api.moonshot.cn/v1",
    model: "moonshot-v1-8k",
    hint: "国内直连，长文本",
  },
  {
    id: "siliconflow",
    name: "硅基流动",
    baseUrl: "https://api.siliconflow.cn/v1",
    model: "Qwen/Qwen2.5-7B-Instruct",
    hint: "国内直连，模型多",
  },
];

export const initialState: WizardState = {
  engine: "offline",
  baseUrl: "",
  model: "",
  apiKey: "",
  topic: "",
  duration: 60,
  aspect: "16:9",
  language: "zh-CN",
  scenes: null,
  captions: true,
  presetId: null,
  notes: "",
  templateId: null,
  styleId: null,
};

export function platformFor(aspect: Aspect, durationSec: number): string {
  if (aspect === "16:9") return "bilibili_16x9";
  if (aspect === "1:1") return "square_1x1";
  // 9:16: the vertical presets differ only in their overlay margins and their
  // duration cap, and 视频号 refuses anything past 60s. Picking the preset whose
  // cap the request actually fits avoids a silent clamp the user never asked
  // for — the warning would be honest, but not needing it is better.
  return durationSec <= 60 ? "wechat_channels_9x16" : "tiktok_9x16";
}

export function buildBody(state: WizardState): CreateVideoBody {
  return {
    prompt: state.topic.trim(),
    language: state.language,
    platform: platformFor(state.aspect, state.duration),
    aspect: state.aspect,
    duration_sec: state.duration,
    scenes: state.scenes ?? undefined,
    template: state.templateId ?? undefined,
    style: state.styleId ?? undefined,
    captions: state.captions,
    writing_preset: state.presetId ?? undefined,
    writing_notes: state.notes.trim() || undefined,
    preset: "balanced",
    wait: false,
    created_by: "studio",
  };
}

/** The same request, as a sentence a human can check before spending 3 minutes. */
export function summarise(state: WizardState, templateName: string,
                          styleName: string, presetName: string): string {
  const parts = [
    state.aspect === "16:9" ? "横屏" : state.aspect === "9:16" ? "竖屏" : "方形",
    `约 ${state.duration} 秒`,
    state.language === "zh-CN" ? "中文旁白" : "英文旁白",
    templateName,
    styleName,
    presetName,
  ];
  return parts.join(" · ");
}
