import { useState, type ReactNode } from "react";
import type {
  JobView,
  LlmStatus,
  SetupItem,
  SetupStatus,
  StyleProfile,
  TemplateManifest,
  TopicSuggestion,
  VideoResult,
  WritingPreset,
} from "../api";
import { api } from "../api";
import { providerLabel, translateError, translateWarning } from "./text";
import {
  ASPECTS,
  DURATIONS,
  LANGUAGES,
  LLM_PRESETS,
  type WizardState,
  platformFor,
} from "./types";

// ---------------------------------------------------------------- primitives
function Dot({ state }: { state: string }) {
  const cls = state === "ready" ? "ok" : state === "unavailable" ? "warn" : "bad";
  const mark = state === "ready" ? "✓" : state === "not_installed" ? "!" : "×";
  return <span className={`wz-dot ${cls}`}>{mark}</span>;
}

function CheckRow({ item }: { item: SetupItem }) {
  return (
    <div className="wz-check">
      <Dot state={item.state} />
      <div>
        <div className="label">
          {item.label}{" "}
          <span className={`wz-badge ${item.state === "ready" ? "ok" : "warn"}`}>
            {item.state_label}
          </span>
        </div>
        <div className="detail">{item.detail}</div>
        {item.fix ? <div className="wz-fix">怎么解决：{item.fix}</div> : null}
      </div>
    </div>
  );
}

function Choice({
  chosen,
  onClick,
  children,
}: {
  chosen: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button className={`wz-choice ${chosen ? "chosen" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function Swatches({ palette }: { palette: Record<string, string> }) {
  const keys = ["bg", "surface", "text", "accent", "accent2"];
  const colors = keys.map((k) => palette[k]).filter(Boolean);
  if (!colors.length) return null;
  return (
    <div className="wz-swatches">
      {colors.map((c, i) => (
        <span key={i} style={{ background: c }} />
      ))}
    </div>
  );
}

// --------------------------------------------------------- step 1: self check
export function StepCheck({
  status,
  loading,
  error,
  onRefresh,
}: {
  status: SetupStatus | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <div className="inner">
      <h2 className="wz-title">先看看这台电脑能不能用</h2>
      <p className="wz-lead">
        下面每一项都是刚才真实检测出来的结果，不是猜测。有问题的项目会告诉你该怎么修。
      </p>

      {loading ? <div className="wz-card">正在检测，第一次打开需要十几秒…</div> : null}
      {error ? <div className="wz-alert bad">{error}</div> : null}

      {status ? (
        <>
          <div className={`wz-alert ${status.ready ? "ok" : "warn"}`}>
            {status.ready
              ? "全部就绪，可以直接开始创作。"
              : `有 ${status.blocking.length} 项需要注意，修好之前生成的视频可能不完整。`}
          </div>
          <div className="wz-card">
            {status.items.map((item) => (
              <CheckRow key={item.id} item={item} />
            ))}
          </div>
          <div className="wz-card wz-quiet">
            <div className="wz-kv">
              程序版本 {status.version}
              <br />
              数据目录 {status.home}
              <br />
              作品目录 {status.outputs}
            </div>
          </div>
          <button className="wz-btn" onClick={onRefresh} disabled={loading}>
            重新检测
          </button>
        </>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------- step 2: AI engine
export function StepEngine({
  status,
  state,
  set,
  onTest,
  testing,
  testResult,
  onSave,
  saving,
}: {
  status: SetupStatus | null;
  state: WizardState;
  set: (patch: Partial<WizardState>) => void;
  onTest: () => void;
  testing: boolean;
  testResult: LlmStatus | null;
  onSave: () => void;
  saving: boolean;
}) {
  const configured = Boolean(status?.llm.configured);
  return (
    <div className="inner">
      <h2 className="wz-title">文案由谁来写</h2>
      <p className="wz-lead">
        这一步决定旁白文案的质量。画面、配音、字幕两种情况都是真实的，只有措辞不同。
      </p>

      <div className="wz-grid two">
        <Choice chosen={state.engine === "offline"} onClick={() => set({ engine: "offline" })}>
          <div className="name">🔌 本地离线（免配置）</div>
          <div className="tagline">
            不联网、不花钱、立刻能用。文案由内置的结构模板生成，通顺但比较通用。
          </div>
          <div className="meta">适合：先把流程跑通、批量做图文书、不想折腾账号</div>
        </Choice>
        <Choice chosen={state.engine === "api"} onClick={() => set({ engine: "api" })}>
          <div className="name">
            🤖 接入自己的 AI（推荐）
            {configured ? <span className="wz-badge ok">已配置</span> : null}
          </div>
          <div className="tagline">
            填一个你自己申请的 API Key，文案会按你选的写作风格真正重写。
          </div>
          <div className="meta">Key 只保存在本机，不会上传到任何第三方服务器</div>
        </Choice>
      </div>

      {state.engine === "api" ? (
        <div className="wz-card" style={{ marginTop: 14 }}>
          <div className="wz-label">快捷填充</div>
          <div className="wz-chips" style={{ marginBottom: 16 }}>
            {LLM_PRESETS.map((preset) => (
              <button
                key={preset.id}
                className="wz-chip"
                title={preset.hint}
                onClick={() => set({ baseUrl: preset.baseUrl, model: preset.model })}
              >
                {preset.name}
              </button>
            ))}
          </div>

          <div className="wz-row">
            <div className="wz-field">
              <label className="wz-label">接口地址</label>
              <input
                type="text"
                value={state.baseUrl}
                placeholder="https://api.deepseek.com/v1"
                onChange={(e) => set({ baseUrl: e.target.value })}
              />
            </div>
            <div className="wz-field">
              <label className="wz-label">模型名称</label>
              <input
                type="text"
                value={state.model}
                placeholder="deepseek-chat"
                onChange={(e) => set({ model: e.target.value })}
              />
            </div>
          </div>

          <div className="wz-field">
            <label className="wz-label">API Key</label>
            <input
              type="password"
              value={state.apiKey}
              placeholder="sk-..."
              autoComplete="off"
              onChange={(e) => set({ apiKey: e.target.value })}
            />
            <div className="wz-help">
              去模型服务商的官网申请，通常形如 sk-开头的字符串。留空保存则等于清除已保存的 Key。
            </div>
          </div>

          <div className="wz-actions-row">
            <button className="wz-btn" onClick={onTest} disabled={testing || !state.apiKey}>
              {testing ? "正在连接…" : "测试连接（不保存）"}
            </button>
            <button
              className="wz-btn primary"
              onClick={onSave}
              disabled={saving || !state.apiKey}
            >
              {saving ? "正在保存…" : "保存并使用"}
            </button>
            {configured ? (
              <span className="wz-badge ok">
                当前已配置 {status?.llm.masked_key} · {status?.llm.model || "默认模型"}
              </span>
            ) : null}
          </div>

          {testResult ? (
            <div className={`wz-alert ${testResult.configured ? "ok" : "bad"}`}>
              {testResult.configured
                ? "连接成功，这个 Key 可以用。"
                : `连接失败：${testResult.reason ?? "原因未知"}`}
              {testResult.configured && testResult.base_url ? (
                <div className="wz-kv">
                  {testResult.base_url} · {testResult.model}
                </div>
              ) : null}
            </div>
          ) : null}

          {testResult?.saved ? (
            <div className="wz-alert ok">已保存到本机配置文件。</div>
          ) : null}
        </div>
      ) : (
        <div className="wz-card wz-quiet" style={{ marginTop: 14 }}>
          {status?.llm.offline_effect ?? "不填也能用：文案由内置模板生成。"}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------- step 3: the idea
export function StepTopic({
  state,
  set,
  suggestions,
  onSuggest,
  suggesting,
}: {
  state: WizardState;
  set: (patch: Partial<WizardState>) => void;
  suggestions: TopicSuggestion[];
  onSuggest: () => void;
  suggesting: boolean;
}) {
  const [showMore, setShowMore] = useState(false);
  return (
    <div className="inner">
      <h2 className="wz-title">你想做什么内容</h2>
      <p className="wz-lead">一句话就行，不用写成标题。写完可以让系统给你几个不同的切入角度。</p>

      <div className="wz-card">
        <div className="wz-field">
          <label className="wz-label">主题</label>
          <textarea
            value={state.topic}
            placeholder="例如：为什么本地跑的 AI 更安全 / 新手第一台相机怎么选 / 我们上季度的复购率变化"
            onChange={(e) => set({ topic: e.target.value })}
          />
          <div className="wz-help">越具体越好。「聊聊 AI」得到的是一段空话，「本地 AI 省下的三笔钱」得到的是一条视频。</div>
        </div>
        <button className="wz-btn" onClick={onSuggest} disabled={suggesting || !state.topic.trim()}>
          {suggesting ? "正在想…" : "帮我想几个角度"}
        </button>

        {suggestions.length ? (
          <div className="wz-grid two" style={{ marginTop: 14 }}>
            {suggestions.map((item) => (
              <Choice
                key={item.title}
                chosen={state.topic === item.title}
                onClick={() => set({ topic: item.title })}
              >
                <div className="name" style={{ fontSize: 13 }}>
                  {item.title}
                </div>
                <div className="tagline">{item.rationale}</div>
                <div className="meta">
                  <span className="wz-badge">{item.angle}</span> {item.video_type}
                </div>
              </Choice>
            ))}
          </div>
        ) : null}
      </div>

      <div className="wz-card">
        <div className="wz-label">成片时长</div>
        <div className="wz-chips" style={{ marginBottom: 18 }}>
          {DURATIONS.map((value) => (
            <button
              key={value}
              className={`wz-chip ${state.duration === value ? "chosen" : ""}`}
              onClick={() => set({ duration: value })}
            >
              {value} 秒
            </button>
          ))}
        </div>

        <div className="wz-label">画面比例</div>
        <div className="wz-grid three">
          {ASPECTS.map((item) => (
            <Choice
              key={item.id}
              chosen={state.aspect === item.id}
              onClick={() => set({ aspect: item.id })}
            >
              <div className="name">{item.label}</div>
              <div className="tagline">{item.where}</div>
            </Choice>
          ))}
        </div>

        <div className="wz-row" style={{ marginTop: 18 }}>
          <div className="wz-field">
            <label className="wz-label">旁白语言</label>
            <select
              value={state.language}
              onChange={(e) => set({ language: e.target.value })}
            >
              {LANGUAGES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className="wz-help">
              只有机器上装了对应语言的语音包才能配音，缺失时视频会没有声音。
            </div>
          </div>
          <div className="wz-field">
            <label className="wz-label">字幕</label>
            <button
              className={`wz-chip ${state.captions ? "chosen" : ""}`}
              onClick={() => set({ captions: !state.captions })}
            >
              {state.captions ? "烧录字幕" : "不要字幕"}
            </button>
            <div className="wz-help">烧录后字幕是画面的一部分，任何播放器都能看到。</div>
          </div>
        </div>

        <button className="wz-btn" onClick={() => setShowMore(!showMore)}>
          {showMore ? "收起高级选项" : "高级选项"}
        </button>
        {showMore ? (
          <div className="wz-field" style={{ marginTop: 14 }}>
            <label className="wz-label">镜头数量（留空由系统决定）</label>
            <input
              type="number"
              min={1}
              max={40}
              value={state.scenes ?? ""}
              placeholder="自动"
              onChange={(e) =>
                set({ scenes: e.target.value ? Number(e.target.value) : null })
              }
            />
            <div className="wz-help">
              镜头越多节奏越快，但每个镜头至少约 3 秒，镜头太少会填不满你设定的时长。
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------- step 4: how it reads
export function StepPreset({
  presets,
  state,
  set,
}: {
  presets: WritingPreset[];
  state: WizardState;
  set: (patch: Partial<WizardState>) => void;
}) {
  const chosen = presets.find((p) => p.id === state.presetId) ?? null;
  return (
    <div className="inner">
      <h2 className="wz-title">用哪种方式讲</h2>
      <p className="wz-lead">
        这里决定的是「话怎么说」。它会改变送给 AI 的写作要求，并给出一套推荐的镜头与配色。
      </p>

      <div className="wz-grid two">
        <Choice
          chosen={state.presetId === null}
          onClick={() => {
            set({ presetId: null });
          }}
        >
          <div className="name">✳ 不指定</div>
          <div className="tagline">用通用的解说口吻，最稳妥。第一次用建议先跑一遍这个。</div>
        </Choice>
        {presets.map((preset) => (
          <Choice
            key={preset.id}
            chosen={state.presetId === preset.id}
            onClick={() => set({ presetId: preset.id })}
          >
            <div className="name">
              {preset.icon} {preset.name}
            </div>
            <div className="tagline">{preset.tagline}</div>
            <div className="meta">
              推荐 {preset.duration_sec}s · {preset.scenes} 个镜头
            </div>
          </Choice>
        ))}
      </div>

      {chosen ? (
        <div className="wz-card" style={{ marginTop: 14 }}>
          <div className="wz-label">{chosen.description}</div>
          <div className="wz-help">
            写给谁看：{chosen.audience}
            <br />
            语气：{chosen.tone}
          </div>
          <div className="wz-label" style={{ marginTop: 14 }}>
            它会强制 AI 遵守的规则
          </div>
          <ul style={{ margin: "6px 0 0 18px", padding: 0, fontSize: 12.5, color: "var(--muted)", lineHeight: 1.75 }}>
            {chosen.rules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
          <div className="wz-label" style={{ marginTop: 14 }}>
            叙事结构
          </div>
          <ol style={{ margin: "6px 0 0 18px", padding: 0, fontSize: 12.5, color: "var(--muted)", lineHeight: 1.75 }}>
            {chosen.structure.map((beat) => (
              <li key={beat}>{beat}</li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="wz-card">
        <div className="wz-field" style={{ marginBottom: 0 }}>
          <label className="wz-label">补充写作要求（可选）</label>
          <textarea
            value={state.notes}
            placeholder="例如：面向完全没接触过这个行业的人；不要出现任何英文术语；结尾不要说「点赞关注」"
            onChange={(e) => set({ notes: e.target.value })}
          />
          <div className="wz-help">
            {state.engine === "api"
              ? "这段要求会优先于预设里的通用规则。"
              : "注意：当前选择了本地离线模式，文案由内置模板生成，这段要求不会生效。要让它生效请回到第 2 步接入 AI。"}
          </div>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------- step 5: the look
export function StepLook({
  templates,
  styles,
  state,
  set,
}: {
  templates: TemplateManifest[];
  styles: StyleProfile[];
  state: WizardState;
  set: (patch: Partial<WizardState>) => void;
}) {
  const chosenTemplate = templates.find((t) => t.id === state.templateId) ?? null;
  return (
    <div className="inner">
      <h2 className="wz-title">长什么样</h2>
      <p className="wz-lead">模板决定视频的结构和节奏，风格决定配色和字体。两者可以自由组合。</p>

      <div className="wz-label">结构模板</div>
      <div className="wz-grid two">
        <Choice
          chosen={state.templateId === null}
          onClick={() => set({ templateId: null })}
        >
          <div className="name">🎯 自动选择（推荐）</div>
          <div className="tagline">系统根据主题、时长和画幅挑选最合适的结构。</div>
        </Choice>
        {templates.map((template) => (
          <Choice
            key={template.id}
            chosen={state.templateId === template.id}
            onClick={() => set({ templateId: template.id })}
          >
            <div className="name">{template.name}</div>
            <div className="tagline">{template.description}</div>
            <div className="meta">
              {template.scene_count.min}-{template.scene_count.max} 个镜头 ·{" "}
              {template.beats.length} 段结构 · 信息密度 {template.density}
            </div>
            {template.not_for.length ? (
              <div className="meta">不适合：{template.not_for.join("、")}</div>
            ) : null}
          </Choice>
        ))}
      </div>

      <div className="wz-label" style={{ marginTop: 20 }}>
        视觉风格
      </div>
      <div className="wz-grid three">
        <Choice chosen={state.styleId === null} onClick={() => set({ styleId: null })}>
          <div className="name">自动</div>
          <div className="tagline">跟随所选模板的默认配色。</div>
        </Choice>
        {styles.map((style) => (
          <Choice
            key={style.id}
            chosen={state.styleId === style.id}
            onClick={() => set({ styleId: style.id })}
          >
            <div className="name">{style.name}</div>
            <div className="tagline">{style.description}</div>
            <Swatches palette={style.palette} />
          </Choice>
        ))}
      </div>

      {chosenTemplate && state.styleId && !chosenTemplate.compatible_styles.includes(state.styleId) ? (
        <div className="wz-alert warn">
          这个风格不在该模板的推荐组合里，通常也能用，但对比度或排版可能不是最佳。
        </div>
      ) : null}
      {platformFor(state.aspect, state.duration) !== "bilibili_16x9" ? (
        <div className="wz-alert warn">
          竖屏和方形平台会在画面底部叠自己的按钮，字幕会自动上移。这是有意的，不是错位。
        </div>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------ step 6: render
export function StepGenerate({
  state,
  job,
  starting,
  error,
  onCancel,
  summary,
}: {
  state: WizardState;
  job: JobView | null;
  starting: boolean;
  error: string | null;
  onCancel: () => void;
  summary: string;
}) {
  const progress = job?.progress ?? 0;
  const stages = job?.tasks ?? [];
  const running = starting || (job != null && job.status !== "completed" && job.status !== "failed");
  return (
    <div className="inner">
      <h2 className="wz-title">生成视频</h2>
      <p className="wz-lead">
        确认一下设置，然后点开始。生成期间可以去做别的事，页面关掉也不会中断服务端任务。
      </p>

      <div className="wz-card">
        <div className="wz-label">本次设置</div>
        <div className="wz-facts">
          <div>
            <b>{state.topic.trim() || "（还没填主题）"}</b>
            <span>主题</span>
          </div>
          <div>
            <b>{state.duration} 秒</b>
            <span>目标时长</span>
          </div>
          <div>
            <b>{state.aspect}</b>
            <span>画面比例</span>
          </div>
        </div>
        <div className="wz-kv" style={{ marginTop: 10 }}>
          {summary}
        </div>
        <div className="wz-kv" style={{ marginTop: 6 }}>
          预计耗时 1-4 分钟（取决于时长、分辨率和机器性能）
        </div>
      </div>

      {running ? (
        <div className="wz-card">
          <div className="wz-label">
            正在生成 {Math.round(progress * 100)}%
          </div>
          <div className="wz-progress">
            <i style={{ width: `${Math.max(3, Math.round(progress * 100))}%` }} />
          </div>
          {stages.length ? (
            stages.map((task) => (
              <div
                key={task.stage}
                className={`wz-stage ${task.status === "running" ? "active" : ""} ${
                  task.status === "completed" ? "done" : ""
                }`}
              >
                <span className="mark">
                  {task.status === "completed" ? "✓" : task.status === "running" ? "▶" : "·"}
                </span>
                <span>{task.name}</span>
                <span style={{ marginLeft: "auto" }}>{Math.round((task.progress ?? 0) * 100)}%</span>
              </div>
            ))
          ) : (
            <div className="wz-stage active">
              <span className="mark">▶</span>
              <span>正在处理，稍等…</span>
            </div>
          )}
          <div className="wz-actions-row">
            <button className="wz-btn danger" onClick={onCancel}>
              取消本次生成
            </button>
          </div>
        </div>
      ) : null}

      {error ? <div className="wz-alert bad">{error}</div> : null}
      {job?.errors?.length ? (
        <div className="wz-alert bad">
          {job.errors.map((item) => translateError(null, item.message)).join("；")}
        </div>
      ) : null}

      {job?.plan ? (
        <details className="wz-details">
          <summary>本次实际使用的方案</summary>
          <pre>{JSON.stringify(job.plan, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------- step 7: done
export function StepResult({
  result,
  job,
  message,
  onReveal,
  onOpen,
  onCopy,
  onAgain,
  onRestart,
}: {
  result: VideoResult;
  job: JobView | null;
  message: string | null;
  onReveal: () => void;
  onOpen: () => void;
  onCopy: () => void;
  onAgain: () => void;
  onRestart: () => void;
}) {
  const fileName = result.video_path
    ? result.video_path.split(/[\\/]/).pop()!
    : null;
  const qc = job?.quality ?? null;
  const checks = job?.quality?.checks ?? [];
  const warned = qc?.warned?.length ?? result.qc?.warned?.length ?? 0;
  const passed = qc?.passed ?? result.qc?.passed ?? null;
  const warnings = [
    ...(result.warnings ?? []),
    ...(job?.fallbacks ?? []).map(
      (item) => `fallback: ${item.stage} ${item.from} → ${item.to}`,
    ),
  ];

  return (
    <div className="inner">
      <h2 className="wz-title">做好了</h2>
      <p className="wz-lead">
        视频已经写入磁盘。下面可以直接播放，也可以打开所在文件夹。
      </p>

      {fileName ? (
        <video className="wz-video" controls src={api.mediaUrl(fileName)} />
      ) : (
        <div className="wz-alert bad">没有生成视频文件。</div>
      )}

      <div className="wz-facts">
        <div>
          <b>
            {result.duration_sec ? `${result.duration_sec.toFixed(1)} 秒` : "—"}
          </b>
          <span>实际时长</span>
        </div>
        <div>
          <b>
            {result.width && result.height ? `${result.width}×${result.height}` : "—"}
          </b>
          <span>分辨率</span>
        </div>
        <div>
          <b>{result.scenes}</b>
          <span>镜头数</span>
        </div>
        <div>
          <b>
            {result.elapsed_sec != null ? `${result.elapsed_sec.toFixed(0)} 秒` : "—"}
          </b>
          <span>生成耗时</span>
        </div>
      </div>

      <div className="wz-card" style={{ marginTop: 14 }}>
        <div className="wz-kv">
          文件 {fileName ?? "—"}
          <br />
          完整路径 {result.video_path ?? "—"}
        </div>
        <div className="wz-actions-row">
          <button className="wz-btn primary" onClick={onOpen}>
            播放视频
          </button>
          <button className="wz-btn" onClick={onReveal}>
            打开文件位置
          </button>
          <button className="wz-btn" onClick={onCopy}>
            复制完整路径
          </button>
        </div>
        {message ? <div className="wz-alert ok">{message}</div> : null}
      </div>

      <div className="wz-card">
        <div className="wz-label">这条视频是怎么来的</div>
        <div className="wz-kv">
          文案 {result.narration_source === "llm" ? "由 AI 模型撰写" : result.narration_source === "user" ? "你提供的文稿" : "内置模板撰写"}
          {result.writing_preset ? ` · 写作预设 ${result.writing_preset}` : ""}
          <br />
          模板 {result.template ?? "—"} · 风格 {result.style ?? "—"}
          <br />
          文案引擎 {providerLabel(result.providers?.llm)}
          <br />
          配音引擎 {providerLabel(result.providers?.tts)}
          <br />
          渲染引擎 {providerLabel(result.providers?.renderer)}
          <br />
          质检 {passed === null ? "未执行" : passed ? "通过" : "未通过"}（警告 {warned} 项）
        </div>

        {warnings.length ? (
          <div>
            <div className="wz-label" style={{ marginTop: 12 }}>
              需要你知道的
            </div>
            {warnings.map((raw, index) => (
              <div key={index} className="wz-alert warn">
                {translateWarning(raw)}
                <details className="wz-details">
                  <summary>原始信息</summary>
                  <pre>{raw}</pre>
                </details>
              </div>
            ))}
          </div>
        ) : (
          <div className="wz-alert ok">没有需要注意的问题。</div>
        )}

        {checks.length ? (
          <details className="wz-details">
            <summary>查看全部质检项（{checks.length} 项）</summary>
            <pre>
              {checks
                .map((check) => `${check.status === "pass" ? "✓" : check.status === "warn" ? "!" : "×"} ${check.name}  ${check.detail}`)
                .join("\n")}
            </pre>
          </details>
        ) : null}

        <details className="wz-details">
          <summary>为什么这样选（可解释的路由理由）</summary>
          <pre>{(result.reasons ?? []).join("\n")}</pre>
        </details>
      </div>

      <div className="wz-actions-row">
        <button className="wz-btn" onClick={onAgain}>
          同样的设置再生成一版
        </button>
        <button className="wz-btn" onClick={onRestart}>
          改一改设置
        </button>
      </div>
    </div>
  );
}
