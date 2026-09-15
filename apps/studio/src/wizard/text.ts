/**
 * Turning the backend's English facts into Chinese a first-time user can act on.
 *
 * The API deliberately keeps its warnings in English — they are the same
 * strings the CLI prints and the regression tests assert on, and translating
 * them at the source would fork one message into two languages that drift.
 * So the translation lives here, at the edge, where it can also be *partial*:
 * an unknown warning is shown verbatim rather than dropped. Hiding a warning
 * because no rule matched it would be the same silent degradation the rest of
 * the product spends its comments preventing.
 */

/** Warning prefixes → Chinese. Ordered: the first match wins. */
const WARNING_RULES: [RegExp, string][] = [
  [
    /^the language model was available but the script call failed/i,
    "已配置的 AI 模型调用失败，本条文案由内置模板生成。详情见下方技术信息。",
  ],
  [
    /^duration_match/i,
    "旁白长度和你设定的目标时长有出入，视频实际时长以旁白为准。",
  ],
  [
    /exceeds .* limit .* clamped/i,
    "你设定的时长超过了所选平台的上限，已自动缩短到上限。",
  ],
  [
    /falls below the per-scene floor/i,
    "镜头数太少，无法填满你设定的时长，已增加镜头。",
  ],
  [
    /overlays its own UI on the lower/i,
    "所选平台会用自己的界面遮挡画面底部，字幕已自动上移避开。",
  ],
  [
    /placeholder/i,
    "本条语音使用了占位音（机器上没有可用的真实语音引擎）。",
  ],
  [
    /no provider/i,
    "没有找到能处理该语言的引擎，相关环节被跳过。",
  ],
  [
    /dry_run/i,
    "这是试运行，没有真正生成视频。",
  ],
  [
    /scene count/i,
    "镜头数与模板建议不一致，已按模板范围调整。",
  ],
  [/fallback/i, "某个环节换了备选方案，结果仍然可用。"],
];

export function translateWarning(raw: string): string {
  for (const [pattern, zh] of WARNING_RULES) {
    if (pattern.test(raw.trim())) return zh;
  }
  return raw;
}

/** Error codes → what the user should do about it. */
const ERROR_RULES: [RegExp, string][] = [
  [/NO_TEMPLATE/i, "指定的模板不存在，请回到「选模板」重新选一个。"],
  [/INVALID_REQUEST/i, "请求参数有问题，请检查主题和时长设置。"],
  [/COMPOSE_FAILED/i, "视频合成失败，通常是磁盘空间不足或 FFmpeg 不可用。"],
  [/QUALITY_FAILED/i, "质检未通过（你开启了严格模式），可以关闭严格模式重试。"],
  [/PLANNING_FAILED/i, "文案规划阶段出错，请换一个更具体的主题再试。"],
  [/TTS|VOICE|SPEECH/i, "语音合成失败，请在环境自检里确认语音引擎是否可用。"],
  [/RENDER/i, "画面渲染失败，请确认系统已安装 Edge 或 Chrome。"],
  [/TIMEOUT/i, "渲染超时。可以先把时长改短、或把运行档位调成 fast 再试。"],
];

export function translateError(code: string | null, message: string | null): string {
  const raw = `${code ?? ""} ${message ?? ""}`;
  for (const [pattern, zh] of ERROR_RULES) {
    if (pattern.test(raw)) return zh;
  }
  return message ?? "未知错误";
}

/** Which entry-point vocabulary the result screen should use. */
export function describeNarration(source: string | null | undefined): string {
  switch (source) {
    case "llm":
      return "由你接入的 AI 模型撰写";
    case "user":
      return "由你提供的文稿";
    case "rule":
      return "由内置模板撰写";
    default:
      return "未记录";
  }
}

export const PROVIDER_LABELS: Record<string, string> = {
  mock_llm: "内置模板（离线）",
  openai_compatible: "AI 模型（API）",
  sapi: "系统语音（Windows SAPI）",
  mock_tts: "占位音（无真实配音）",
  moss: "MOSS 语音",
  advanced_html: "高级渲染器",
  legacy_html: "兼容渲染器",
  mock_renderer: "占位渲染器",
  srt: "字幕文件",
  local_asset: "本地素材",
};

export function providerLabel(id: string | null | undefined): string {
  if (!id) return "—";
  return PROVIDER_LABELS[id] ? `${PROVIDER_LABELS[id]}（${id}）` : id;
}
