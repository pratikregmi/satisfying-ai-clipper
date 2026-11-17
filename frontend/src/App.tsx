import { useCallback, useEffect, useRef, useState } from "react";

import "./App.css";

const VIDEO_ID = 2;
const PAGE_SIZE = 50;

type Video = {
  id: number;
  original_filename: string;
  duration: number;
  width: number;
  height: number;
  frame_rate: string;
  file_size: number;
  has_audio: boolean;
};

type TranscriptSegment = {
  id: number;
  start_time: number;
  end_time: number;
  text: string;
  overlap_duration: number;
};

type Scene = {
  id: number;
  video_id: number;
  scene_number: number;
  start_time: number;
  end_time: number;
  duration: number;
  thumbnail_url: string | null;
  transcript_segments: TranscriptSegment[];
};

type SceneTranscriptPage = {
  video_id: number;
  total_scenes: number;
  limit: number;
  offset: number;
  scenes: {
    scene_id: number;
    scene_number: number;
    start_time: number;
    end_time: number;
    duration: number;
    thumbnail_url: string | null;
    transcript_segments: TranscriptSegment[];
  }[];
};

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;

  if (hours > 0) {
    return `${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }

  return `${minutes.toString().padStart(2, "0")}:${secs
    .toString()
    .padStart(2, "0")}`;
}

function formatSize(bytes: number) {
  if (!bytes) return "Unknown size";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function App() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScenes, setSelectedScenes] = useState<number[]>([]);
  const [currentScene, setCurrentScene] = useState<Scene | null>(null);
  const [offset, setOffset] = useState(0);
  const [totalScenes, setTotalScenes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadVideo = useCallback(async () => {
    const response = await fetch(`/api/videos/${VIDEO_ID}`);
    if (!response.ok) {
      throw new Error("Could not load video information.");
    }
    const data = await response.json();
    setVideo(data);
  }, []);

  const loadScenes = useCallback(async (pageOffset: number) => {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `/api/videos/${VIDEO_ID}/scene-transcripts?limit=${PAGE_SIZE}&offset=${pageOffset}`
      );

      if (!response.ok) {
        throw new Error("Could not load scenes and transcripts.");
      }

      const data: SceneTranscriptPage = await response.json();

      const mappedScenes: Scene[] = data.scenes.map((scene) => ({
        id: scene.scene_id,
        video_id: data.video_id,
        scene_number: scene.scene_number,
        start_time: scene.start_time,
        end_time: scene.end_time,
        duration: scene.duration,
        thumbnail_url: scene.thumbnail_url,
        transcript_segments: scene.transcript_segments,
      }));

      setScenes(mappedScenes);
      setTotalScenes(data.total_scenes);
      setOffset(data.offset);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Something went wrong."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadVideo().catch((err) => {
      setError(
        err instanceof Error ? err.message : "Could not load video."
      );
    });
    loadScenes(0);
  }, [loadVideo, loadScenes]);

  const selectScene = (scene: Scene) => {
    setCurrentScene(scene);
    if (videoRef.current) {
      videoRef.current.currentTime = scene.start_time;
      videoRef.current.play().catch(() => {
        // Playback can require a direct user interaction in some browsers.
      });
    }
  };

  const toggleSelection = (sceneId: number) => {
    setSelectedScenes((previous) =>
      previous.includes(sceneId)
        ? previous.filter((id) => id !== sceneId)
        : [...previous, sceneId]
    );
  };

  const totalPages = Math.max(1, Math.ceil(totalScenes / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">S</div>
          <div>
            <h1>SatisfyingAI</h1>
            <span>LOCAL VIDEO STUDIO</span>
          </div>
        </div>

        <nav className="navigation">
          <div className="nav-label">WORKSPACE</div>
          <a className="nav-item active" href="#dashboard">
            <span>▦</span> Scene Browser
          </a>
          <div className="nav-item disabled">
            <span>◈</span> AI Analysis
            <small>Coming soon</small>
          </div>
          <div className="nav-item disabled">
            <span>✂</span> Clip Editor
            <small>Coming soon</small>
          </div>
          <div className="nav-item disabled">
            <span>▤</span> Exports
            <small>Coming soon</small>
          </div>
        </nav>

        <div className="sidebar-bottom">
          <div className="local-status">
            <span className="status-dot" />
            <div>
              <strong>Local processing</strong>
              <small>Your files stay on this Mac</small>
            </div>
          </div>
          <div className="sidebar-version">SATISFYINGAI · v0.4.0</div>
        </div>
      </aside>

      <section className="main-content" id="dashboard">
        <header className="topbar">
          <div>
            <div className="breadcrumb">Workspace / Videos / Scene Browser</div>
            <h2>Scene Browser</h2>
          </div>
          <div className="topbar-right">
            <span className="connection">
              <span className="status-dot" /> Backend connected
            </span>
            <div className="avatar">SA</div>
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section className="video-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">YOUR VIDEO</div>
              <h3>{video?.original_filename || "Loading video..."}</h3>
              <p>Review your video and explore its detected scenes.</p>
            </div>
            <div className="video-tag">VIDEO #{VIDEO_ID}</div>
          </div>

          <div className="video-layout">
            <div className="player-card">
              <div className="player-frame">
                <video
                  ref={videoRef}
                  controls
                  preload="metadata"
                  src={`/api/videos/${VIDEO_ID}/stream`}
                />
              </div>
              <div className="player-footer">
                <div>
                  <strong>
                    {currentScene
                      ? `Scene ${currentScene.scene_number}`
                      : "Video preview"}
                  </strong>
                  <span>
                    {currentScene
                      ? `${formatTime(currentScene.start_time)} – ${formatTime(
                          currentScene.end_time
                        )}`
                      : "Select a scene to jump to that moment."}
                  </span>
                </div>
                <span className="quality-tag">
                  {video ? `${video.width} × ${video.height}` : "—"}
                </span>
              </div>
            </div>

            <div className="video-info-card">
              <div className="eyebrow">VIDEO INFORMATION</div>
              <div className="info-row">
                <span>Duration</span>
                <strong>{video ? formatTime(video.duration) : "—"}</strong>
              </div>
              <div className="info-row">
                <span>Resolution</span>
                <strong>
                  {video ? `${video.width} × ${video.height}` : "—"}
                </strong>
              </div>
              <div className="info-row">
                <span>Frame rate</span>
                <strong>{video?.frame_rate || "—"}</strong>
              </div>
              <div className="info-row">
                <span>File size</span>
                <strong>{video ? formatSize(video.file_size) : "—"}</strong>
              </div>
              <div className="info-row">
                <span>Audio</span>
                <strong>
                  {video ? (video.has_audio ? "Available" : "None") : "—"}
                </strong>
              </div>
              <div className="info-row">
                <span>Detected scenes</span>
                <strong>{totalScenes.toLocaleString()}</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="scenes-section">
          <div className="scenes-heading">
            <div>
              <div className="eyebrow">VIDEO BREAKDOWN</div>
              <h3>Detected scenes</h3>
              <p>Choose a scene to preview it, or select multiple scenes.</p>
            </div>
            <div className="selection-count">
              <strong>{selectedScenes.length}</strong>
              <span>selected</span>
            </div>
          </div>

          <div className="scene-toolbar">
            <span>
              Showing {scenes.length ? offset + 1 : 0}–
              {Math.min(offset + scenes.length, totalScenes)} of {totalScenes} scenes
            </span>
            <span>50 scenes per page</span>
          </div>

          {loading ? (
            <div className="loading-state">Loading your scenes...</div>
          ) : scenes.length === 0 ? (
            <div className="loading-state">
              No scenes found. Run scene detection in the backend first.
            </div>
          ) : (
            <div className="scene-grid">
              {scenes.map((scene) => {
                const selected = selectedScenes.includes(scene.id);
                const active = currentScene?.id === scene.id;

                return (
                  <article
                    className={`scene-card ${active ? "current" : ""} ${
                      selected ? "selected" : ""
                    }`}
                    key={scene.id}
                  >
                    <button
                      className="scene-preview"
                      onClick={() => selectScene(scene)}
                      title={`Preview scene ${scene.scene_number}`}
                    >
                      {scene.thumbnail_url ? (
                        <img
                          src={scene.thumbnail_url}
                          alt={`Scene ${scene.scene_number}`}
                          loading="lazy"
                        />
                      ) : (
                        <div className="thumbnail-placeholder">
                          Thumbnail unavailable
                        </div>
                      )}
                      <span className="scene-play">▶</span>
                      <span className="scene-number">#{scene.scene_number}</span>
                    </button>

                    <div className="scene-details">
                      <div>
                        <strong>Scene {scene.scene_number}</strong>
                        <span>{formatTime(scene.start_time)}</span>
                      </div>
                      <label className="scene-checkbox">
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleSelection(scene.id)}
                          aria-label={`Select scene ${scene.scene_number}`}
                        />
                        <span />
                      </label>
                    </div>

                    <div className="scene-duration">
                      Duration: {scene.duration.toFixed(2)} sec
                    </div>

                    <div className="scene-transcript">
                      <div className="transcript-heading">
                        <span>DETECTED DIALOGUE</span>
                        <span>{scene.transcript_segments.length} segments</span>
                      </div>

                      {scene.transcript_segments.length > 0 ? (
                        <div className="transcript-list">
                          {scene.transcript_segments.map((segment) => (
                            <div
                              className="transcript-segment"
                              key={segment.id}
                            >
                              <span className="transcript-time">
                                {formatTime(segment.start_time)}
                              </span>
                              <p>{segment.text}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="no-transcript">
                          No dialogue detected in this scene.
                        </p>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          <div className="pagination">
            <button
              disabled={currentPage <= 1 || loading}
              onClick={() => loadScenes(Math.max(0, offset - PAGE_SIZE))}
            >
              ← Previous
            </button>
            <span>
              Page <strong>{currentPage}</strong> of {totalPages}
            </span>
            <button
              disabled={currentPage >= totalPages || loading}
              onClick={() => loadScenes(offset + PAGE_SIZE)}
            >
              Next →
            </button>
          </div>
        </section>

        <footer className="footer">
          <span>SatisfyingAI · Local AI Video Studio</span>
          <span>Built for private, local-first video workflows.</span>
        </footer>
      </section>
    </main>
  );
}

export default App;
