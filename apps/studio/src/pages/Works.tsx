import { useCallback, useEffect, useState } from "react";
import type { OutputItem } from "../api";
import { ApiError, api } from "../api";

/**
 * 我的作品 — the file manager the render never had.
 *
 * Deliberately reads the filesystem through the API rather than keeping its own
 * index: a video that the user deleted, moved or copied must not keep showing up
 * here as if it were still there. The list is a view of what exists, not a
 * record of what once happened.
 */
export default function Works({ onCreate }: { onCreate: () => void }) {
  const [items, setItems] = useState<OutputItem[]>([]);
  const [directory, setDirectory] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [playing, setPlaying] = useState<OutputItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.outputs();
      setItems(payload.items);
      setDirectory(payload.directory);
    } catch (err) {
      setError(describe(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (kind: "reveal" | "open", path: string, name: string) => {
    setMessage(null);
    try {
      const res = kind === "reveal" ? await api.reveal(path) : await api.openPath(path);
      setMessage(`${name}：${res.detail}`);
    } catch (err) {
      setMessage(`${name}：${describe(err)}。路径是 ${path}，可以手动打开。`);
    }
  };

  return (
    <div>
      <h2 className="page-title">我的作品</h2>
      <p className="page-sub">
        共 {items.length} 条。列表直接读取磁盘，你在文件管理器里删掉的文件不会留在这里。
      </p>

      <div style={{ display: "flex", gap: 10, marginBottom: 18 }}>
        <button className="wz-btn primary" onClick={onCreate}>
          去做一条新视频
        </button>
        <button className="wz-btn" onClick={load} disabled={loading}>
          {loading ? "刷新中…" : "刷新列表"}
        </button>
        <span className="wz-kv" style={{ alignSelf: "center" }}>
          {directory}
        </span>
      </div>

      {message ? <div className="wz-alert ok">{message}</div> : null}
      {error ? <div className="wz-alert bad">读取失败：{error}</div> : null}

      {playing ? (
        <div className="wz-card">
          <div className="wz-label">{playing.title}</div>
          <video className="wz-video" controls autoPlay src={api.mediaUrl(playing.name)} />
          <div className="wz-actions-row">
            <button className="wz-btn" onClick={() => setPlaying(null)}>
              关闭播放
            </button>
            <button
              className="wz-btn"
              onClick={() => void act("reveal", playing.path, playing.name)}
            >
              打开文件位置
            </button>
          </div>
        </div>
      ) : null}

      {!loading && !items.length && !error ? (
        <div className="wz-empty">
          还没有作品。回到「开始创作」，第一条约 1-4 分钟就能出来。
        </div>
      ) : null}

      <div className="wz-works" style={{ marginTop: 16 }}>
        {items.map((item) => (
          <div className="wz-work" key={item.name}>
            <div
              className="thumb"
              style={
                item.thumbnail
                  ? { backgroundImage: `url(${api.mediaUrl(thumbnailName(item))})` }
                  : undefined
              }
            >
              {item.thumbnail ? null : "没有缩略图"}
            </div>
            <div className="body">
              <b>{item.title || item.name}</b>
              <div className="sub">
                {item.size_mb} MB · {formatTime(item.created_at)}
              </div>
              <div className="wz-actions-row" style={{ marginTop: "auto" }}>
                <button className="wz-btn" onClick={() => setPlaying(item)}>
                  播放
                </button>
                <button
                  className="wz-btn"
                  onClick={() => void act("reveal", item.path, item.name)}
                >
                  打开位置
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The thumbnail is a sibling file the compose stage writes next to the video. */
function thumbnailName(item: OutputItem): string {
  return `${item.name.replace(/\.mp4$/i, "")}.jpg`;
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return `HTTP ${error.status} ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}
