import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  JobView,
  LlmStatus,
  SetupStatus,
  StyleProfile,
  TemplateManifest,
  TopicSuggestion,
  VideoResult,
  WritingPreset,
} from "../api";
import { ApiError, api } from "../api";
import { StepCheck, StepEngine, StepGenerate, StepLook, StepPreset, StepResult, StepTopic } from "./steps";
import { translateError } from "./text";
import { buildBody, initialState, summarise, type Aspect, type WizardState } from "./types";
import "./wizard.css";

const STEPS = [
  { id: "check", title: "环境自检", hint: "这台电脑能不能用" },
  { id: "engine", title: "文案引擎", hint: "谁来写旁白" },
  { id: "topic", title: "选题", hint: "做什么内容" },
  { id: "preset", title: "写作风格", hint: "用哪种方式讲" },
  { id: "look", title: "模板与配色", hint: "长什么样" },
  { id: "render", title: "生成", hint: "开始做视频" },
  { id: "done", title: "完成", hint: "播放与保存" },
];

const ASPECT_BY_PLATFORM: Record<string, Aspect> = {
  bilibili_16x9: "16:9",
  youtube_16x9: "16:9",
  x_16x9: "16:9",
  tiktok_9x16: "9:16",
  wechat_channels_9x16: "9:16",
  instagram_reels_9x16: "9:16",
  square_1x1: "1:1",
};

/**
 * The step lives in the URL (`#create/3`), so a refresh during a four-minute
 * render does not send the user back to the beginning, and "the page broke on
 * step 5" is a link someone can send us.
 */
function stepFromHash(): number {
  const raw = Number(window.location.hash.replace("#", "").split("/")[1]);
  if (!Number.isInteger(raw) || raw < 0 || raw > 5) return 0;
  return raw;
}

export default function Wizard({ onWorksLoaded }: { onWorksLoaded?: (n: number) => void }) {
  const [step, setStepRaw] = useState(stepFromHash);
  const [state, setState] = useState<WizardState>(initialState);
  const [note, setNote] = useState<string | null>(null);

  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [checking, setChecking] = useState(true);
  const [checkError, setCheckError] = useState<string | null>(null);

  const [templates, setTemplates] = useState<TemplateManifest[]>([]);
  const [styles, setStyles] = useState<StyleProfile[]>([]);
  const [presets, setPresets] = useState<WritingPreset[]>([]);

  const [suggestions, setSuggestions] = useState<TopicSuggestion[]>([]);
  const [suggesting, setSuggesting] = useState(false);

  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<LlmStatus | null>(null);

  const [starting, setStarting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [result, setResult] = useState<VideoResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  /** Fields the user set by hand. A preset may never overwrite these. */
  const touched = useRef<Set<keyof WizardState>>(new Set());

  const setStep = useCallback((next: number | ((prev: number) => number)) => {
    setStepRaw((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      const clamped = Math.max(0, Math.min(6, value));
      // replaceState, not pushState: seven wizard steps should not become seven
      // entries in the back button.
      window.history.replaceState(null, "", `#create/${clamped}`);
      return clamped;
    });
  }, []);

  // ----------------------------------------------------------------- loading
  const loadStatus = useCallback(async () => {
    setChecking(true);
    setCheckError(null);
    try {
      setStatus(await api.setupStatus());
    } catch (error) {
      setCheckError(`无法连接本地服务：${describe(error)}`);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    void (async () => {
      try {
        const [t, s, p, o] = await Promise.all([
          api.templates(),
          api.styles(),
          api.presets(),
          api.outputs(),
        ]);
        setTemplates(t);
        setStyles(s);
        setPresets(p);
        onWorksLoaded?.(o.items.length);
      } catch {
        // The catalogue is not fatal: the wizard still works, it just falls
        // back to "auto" for everything. Saying nothing is worse than a blank
        // list, so the empty state text covers it.
      }
    })();
  }, [loadStatus, onWorksLoaded]);

  // ------------------------------------------------------------------ update
  const set = useCallback(
    (patch: Partial<WizardState>) => {
      if (patch.presetId === undefined) {
        for (const key of Object.keys(patch)) touched.current.add(key as keyof WizardState);
        setState((prev) => ({ ...prev, ...patch }));
        return;
      }
      const preset = presets.find((item) => item.id === patch.presetId) ?? null;
      const applied: string[] = [];
      setState((prev) => {
        const next = { ...prev, ...patch };
        if (!preset) return next;
        // A preset is a set of *recommendations*: it fills the fields the user
        // has not touched and leaves the rest alone. Letting it overwrite a
        // hand-picked 方形 1:1 because the preset recommends 16:9 is exactly the
        // kind of silent "help" that makes people stop trusting defaults.
        if (preset.duration_sec && !touched.current.has("duration")) {
          next.duration = preset.duration_sec;
          applied.push(`${preset.duration_sec} 秒`);
        }
        if (preset.scenes && !touched.current.has("scenes")) {
          next.scenes = preset.scenes;
          applied.push(`${preset.scenes} 个镜头`);
        }
        const aspect = preset.platform ? ASPECT_BY_PLATFORM[preset.platform] : undefined;
        if (aspect && !touched.current.has("aspect")) {
          next.aspect = aspect;
          applied.push(aspect);
        }
        if (!touched.current.has("templateId") && preset.template) {
          next.templateId = preset.template;
          applied.push("结构模板");
        }
        if (!touched.current.has("styleId") && preset.style) {
          next.styleId = preset.style;
          applied.push("配色");
        }
        return next;
      });
      setNote(
        !preset
          ? null
          : applied.length
            ? `已按「${preset.name}」调整：${applied.join(" · ")}。后面几步都可以改。`
            : `「${preset.name}」的推荐值和你已经选好的设置冲突，保留你的选择。`,
      );
    },
    [presets],
  );

  // ------------------------------------------------------------- LLM actions
  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(
        await api.testLlm({
          api_key: state.apiKey,
          base_url: state.baseUrl || null,
          model: state.model || null,
        }),
      );
    } catch (error) {
      setTestResult({
        provider: "openai_compatible",
        state: "error",
        state_label: "出错",
        configured: false,
        reason: describe(error),
        base_url: state.baseUrl,
        model: state.model,
        masked_key: "",
        offline_effect: "",
      });
    } finally {
      setTesting(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    setTestResult(null);
    try {
      const next = await api.saveLlm({
        api_key: state.apiKey,
        base_url: state.baseUrl || null,
        model: state.model || null,
      });
      setTestResult(next);
      setStatus(await api.setupStatus());
      setNote(
        next.configured
          ? "API Key 已保存并生效，文案将由你的模型撰写。"
          : "已保存到本机，但连接测试没有通过——生成时会自动回退到内置模板，并在结果页告诉你原因。",
      );
    } catch (error) {
      setTestResult({
        provider: "openai_compatible",
        state: "error",
        state_label: "出错",
        configured: false,
        reason: describe(error),
        base_url: state.baseUrl,
        model: state.model,
        masked_key: "",
        offline_effect: "",
      });
    } finally {
      setSaving(false);
    }
  };

  const onSuggest = async () => {
    setSuggesting(true);
    try {
      setSuggestions(await api.suggestTopics(state.topic, 4));
    } catch (error) {
      setNote(`想角度失败了：${describe(error)}`);
    } finally {
      setSuggesting(false);
    }
  };

  // ------------------------------------------------------------------- job
  /**
   * Poll the *job* while it runs and the *video* once it is done.
   *
   * Two endpoints on purpose: the job carries the live stage list the progress
   * UI needs, and the video result carries the product-shaped answer (real
   * duration probed off the finished file, the video's own warnings). Asking
   * one of them for the other's job is how a UI ends up showing a progress bar
   * for a render that already finished.
   */
  const poll = useCallback(async (id: string) => {
    try {
      const view = await api.job(id);
      setJob(view);
      if (view.status === "completed") {
        const res = await api.video(id);
        if (res.ok && res.video_path) {
          setResult(res);
          setStep(6);
        } else {
          setRunError(translateError(res.error_code, res.error));
        }
        return true;
      }
      if (view.status === "failed") {
        setRunError(translateError(null, view.errors[0]?.message ?? "生成失败"));
        return true;
      }
      if (view.status === "cancelled") {
        setRunError("已取消本次生成。");
        return true;
      }
      return false;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setRunError("任务不存在，可能服务被重启过。请重新生成。");
        return true;
      }
      return false;
    }
  }, []);

  useEffect(() => {
    if (!jobId) return;
    const tick = async () => {
      const done = await poll(jobId);
      if (done && timer.current) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    };
    void tick();
    timer.current = window.setInterval(tick, 1500);
    return () => {
      if (timer.current) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    };
  }, [jobId, poll]);

  const start = async () => {
    setStarting(true);
    setRunError(null);
    setResult(null);
    setJob(null);
    setJobId(null);
    setMsg(null);
    try {
      const res = await api.createVideo(buildBody(state));
      if (!res.ok) {
        setRunError(translateError(res.error_code, res.error));
        return;
      }
      if (res.video_path) {
        // A synchronous answer. Happens only if `wait` was not honoured; the
        // result screen is the same one either way.
        setResult(res);
        setStep(6);
        return;
      }
      setJobId(res.job_id);
    } catch (error) {
      setRunError(`无法开始生成：${describe(error)}`);
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!jobId) return;
    try {
      await api.cancelJob(jobId);
      setNote("已请求取消，正在等待服务端收尾。");
    } catch (error) {
      setRunError(`取消失败：${describe(error)}`);
    }
  };

  const desktop = async (kind: "reveal" | "open", path: string) => {
    setMsg(null);
    try {
      const res = kind === "reveal" ? await api.reveal(path) : await api.openPath(path);
      setMsg(`已执行：${res.detail}。如果没有弹出窗口，请手动打开上面的路径。`);
    } catch (error) {
      setMsg(
        `打不开：${describe(error)}。路径已经显示在下面，可以手动复制到文件管理器打开。`,
      );
    }
  };

  const copyPath = async () => {
    const path = result?.video_path;
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      setMsg("路径已复制到剪贴板。");
    } catch {
      setMsg(`浏览器不允许自动复制，请手动选中：${path}`);
    }
  };

  // ------------------------------------------------------------------ render
  const summary = useMemo(() => {
    const templateName =
      templates.find((t) => t.id === state.templateId)?.name ?? "自动模板";
    const styleName = styles.find((s) => s.id === state.styleId)?.name ?? "自动风格";
    const presetName =
      presets.find((p) => p.id === state.presetId)?.name ?? "通用口吻";
    return summarise(state, templateName, styleName, presetName);
  }, [templates, styles, presets, state]);

  const topicMissing = !state.topic.trim();
  const blocked = step === 2 && topicMissing;
  const running =
    starting || (jobId != null && job?.status !== "completed" && job?.status !== "failed");

  const canAdvance = () => {
    if (step === 2) return !topicMissing;
    if (step === 5) return false;
    if (step === 6) return false;
    return true;
  };

  const footer = () => {
    if (step === 5) {
      return (
        <>
          <button className="wz-btn" onClick={() => setStep(4)}>
            上一步
          </button>
          <span className="spacer" />
          <span className="status">
            {running ? "正在生成，请保持本页面打开或直接关掉都行。" : note ?? ""}
          </span>
          <button
            className="wz-btn primary big"
            onClick={start}
            disabled={running || topicMissing}
          >
            {running ? "生成中…" : "开始生成"}
          </button>
        </>
      );
    }
    if (step === 6) {
      return (
        <>
          <span className="status">{msg ?? ""}</span>
          <span className="spacer" />
          <button className="wz-btn" onClick={() => setStep(4)}>
            改设置重做
          </button>
        </>
      );
    }
    return (
      <>
        <button
          className="wz-btn"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0}
        >
          上一步
        </button>
        <span className="spacer" />
        <span className="status">
          {blocked
            ? "先填一个主题再继续。"
            : step === 0 && status && !status.ready
              ? `有 ${status.blocking.length} 项需要注意。仍然可以继续，但成片可能没有声音或没有画面。`
              : (note ?? "")}
        </span>
        <button
          className="wz-btn primary"
          onClick={() => setStep((s) => s + 1)}
          disabled={!canAdvance()}
        >
          {step === 4 ? "下一步：生成" : "下一步"}
        </button>
      </>
    );
  };

  return (
    <div className="wz">
      <div className="wz-steps">
        {STEPS.map((item, index) => {
          // The last step is a result, not a place: it becomes reachable when
          // there is something to show, never before.
          const reachable = index <= 5;
          return (
            <button
              key={item.id}
              className={`wz-step ${step === index ? "current" : ""} ${
                index < step ? "done" : ""
              }`}
              onClick={() => reachable && setStep(index)}
              disabled={!reachable}
            >
              <span className="num">{index < step ? "✓" : index + 1}</span>
              <span className="txt">
                {item.title}
                <span className="hint">{item.hint}</span>
              </span>
            </button>
          );
        })}
      </div>

      <main className="wz-main">
        <div className="wz-body">
          {step === 0 ? (
            <StepCheck
              status={status}
              loading={checking}
              error={checkError}
              onRefresh={() => void loadStatus()}
            />
          ) : null}
          {step === 1 ? (
            <StepEngine
              status={status}
              state={state}
              set={set}
              onTest={() => void onTest()}
              testing={testing}
              testResult={testResult}
              onSave={() => void onSave()}
              saving={saving}
            />
          ) : null}
          {step === 2 ? (
            <StepTopic
              state={state}
              set={set}
              suggestions={suggestions}
              onSuggest={() => void onSuggest()}
              suggesting={suggesting}
            />
          ) : null}
          {step === 3 ? <StepPreset presets={presets} state={state} set={set} /> : null}
          {step === 4 ? (
            <StepLook templates={templates} styles={styles} state={state} set={set} />
          ) : null}
          {step === 5 ? (
            <StepGenerate
              state={state}
              job={job}
              starting={starting}
              error={runError}
              onCancel={() => void cancel()}
              summary={summary}
            />
          ) : null}
          {step === 6 && result ? (
            <StepResult
              result={result}
              job={job}
              message={msg}
              onReveal={() => void desktop("reveal", result.video_path ?? "")}
              onOpen={() => void desktop("open", result.video_path ?? "")}
              onCopy={() => void copyPath()}
              onAgain={() => {
                setMsg(null);
                void start();
              }}
              onRestart={() => {
                setMsg(null);
                setStep(4);
              }}
            />
          ) : null}
        </div>
        <div className="wz-actions">{footer()}</div>
      </main>
    </div>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return `HTTP ${error.status} ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}
