
import { useCallback, useEffect, useRef, useState } from "react";

import "./App.css";

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

type GeneratedClipFile = {
  filename: string;
  url: string;
  size_bytes: number;
};

type ClipMetadata = {
  id: number;
  candidate_id: number;
  title: string;
  description: string;
  hashtags: string[];
  status: "pending" | "generating" | "completed" | "failed";
  model_name: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type ClipMetadataDraft = {
  title: string;
  description: string;
  hashtags: string;
};

type GeneratedClip = {
  candidate_id: number;
  review: GeneratedClipFile | null;
  shorts: GeneratedClipFile | null;
  full: GeneratedClipFile | null;
  metadata: ClipMetadata | null;
};

type GeneratedClipsResponse = {
  video_id: number;
  total: number;
  clips: GeneratedClip[];
};

type PipelineStatusResponse = {
  job_id: number;
  video_id: number;
  status: string;
  current_stage: string;
  progress_percent: number;
  error_message: string | null;
};

type ActivePipeline = {
  videoId: number;
  jobId: number;
};

type IngestVideoResponse = {
  message: string;
  video_id: number;
  job_id: number;
  original_filename: string;
  duration: number;
  status: string;
  current_stage: string;
  progress_percent: number;
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

  const [videos, setVideos] = useState<Video[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const video = videos.find((item) => item.id === selectedVideoId) ?? null;

  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScenes, setSelectedScenes] = useState<number[]>([]);
  const [currentScene, setCurrentScene] = useState<Scene | null>(null);
  const [offset, setOffset] = useState(0);
  const [totalScenes, setTotalScenes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [clips, setClips] = useState<GeneratedClip[]>([]);
  const [clipLoading, setClipLoading] = useState(false);
  const [clipError, setClipError] = useState("");
  const [metadataDrafts, setMetadataDrafts] = useState<
    Record<number, ClipMetadataDraft>
  >({});
  const [metadataGeneratingId, setMetadataGeneratingId] = useState<number | null>(null);
  const [metadataSavingId, setMetadataSavingId] = useState<number | null>(null);
  const [metadataMessages, setMetadataMessages] = useState<
    Record<number, string>
  >({});

  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState("");

  const [activePipeline, setActivePipeline] =
    useState<ActivePipeline | null>(null);

  const [pipelineStatus, setPipelineStatus] =
    useState<PipelineStatusResponse | null>(null);

  // Load videos and return the data so startup can recover
  // an existing pipeline after a browser refresh.
  const loadVideos = useCallback(
    async (preferredVideoId?: number): Promise<Video[]> => {
      const response = await fetch("/api/videos/");

      if (!response.ok) {
        throw new Error("Could not load your video library.");
      }

      const data: Video[] = await response.json();

      setVideos(data);

      if (data.length > 0) {
        const preferredVideo =
          data.find((item) => item.id === preferredVideoId) ??
          data.find((item) => item.id === 2) ??
          data[0];

        setSelectedVideoId(preferredVideo.id);
      } else {
        setLoading(false);
      }

      return data;
    },
    []
  );

  const loadScenes = useCallback(
    async (videoId: number, pageOffset: number) => {
      setLoading(true);
      setError("");

      try {
        const response = await fetch(
          `/api/videos/${videoId}/scene-transcripts?limit=${PAGE_SIZE}&offset=${pageOffset}`
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
        setScenes([]);
        setTotalScenes(0);
        setError(
          err instanceof Error ? err.message : "Something went wrong."
        );
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const loadClips = useCallback(async (videoId: number) => {
    setClipLoading(true);
    setClipError("");

    try {
      const response = await fetch(`/api/videos/${videoId}/clips`);

      if (!response.ok) {
        throw new Error("Could not load generated clips.");
      }

      const data: GeneratedClipsResponse = await response.json();

      const loadedClips = data.clips ?? [];
      setClips(loadedClips);

      setMetadataDrafts(
        Object.fromEntries(
          loadedClips.map((clip) => [
            clip.candidate_id,
            {
              title: clip.metadata?.title ?? "",
              description: clip.metadata?.description ?? "",
              hashtags: clip.metadata?.hashtags.join(" ") ?? "",
            },
          ])
        )
      );
      setMetadataMessages({});
    } catch (err) {
      setClips([]);
      setClipError(
        err instanceof Error ? err.message : "Could not load generated clips."
      );
    } finally {
      setClipLoading(false);
    }
  }, []);

  const generateClipMetadata = async (candidateId: number) => {
    if (selectedVideoId === null || metadataGeneratingId !== null) return;

    setMetadataGeneratingId(candidateId);
    setMetadataMessages((current) => ({
      ...current,
      [candidateId]: "Generating metadata with AI...",
    }));

    try {
      const response = await fetch(
        `/api/videos/${selectedVideoId}/clips/${candidateId}/metadata/generate`,
        { method: "POST" }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Metadata generation failed.");
      }

      const metadata = data as ClipMetadata;

      if (metadata.status !== "completed") {
        throw new Error(
          metadata.error_message || "AI could not generate metadata."
        );
      }

      setClips((current) =>
        current.map((clip) =>
          clip.candidate_id === candidateId
            ? { ...clip, metadata }
            : clip
        )
      );

      setMetadataDrafts((current) => ({
        ...current,
        [candidateId]: {
          title: metadata.title,
          description: metadata.description,
          hashtags: metadata.hashtags.join(" "),
        },
      }));

      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: "Metadata generated successfully. Review and save your changes.",
      }));
    } catch (err) {
      setMetadataMessages((current) => ({
        ...current,
        [candidateId]:
          err instanceof Error ? err.message : "Metadata generation failed.",
      }));
    } finally {
      setMetadataGeneratingId(null);
    }
  };

  const saveClipMetadata = async (candidateId: number) => {
    if (selectedVideoId === null || metadataSavingId !== null) return;

    const draft = metadataDrafts[candidateId];

    if (!draft) return;

    const hashtags = draft.hashtags
      .split(/[\\s,]+/)
      .map((tag) => tag.trim().replace(/^#+/, ""))
      .filter(Boolean);

    if (!draft.title.trim() || !draft.description.trim()) {
      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: "Title and description cannot be empty.",
      }));
      return;
    }

    if (hashtags.length < 3 || hashtags.length > 8) {
      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: "Please provide between 3 and 8 hashtags.",
      }));
      return;
    }

    setMetadataSavingId(candidateId);
    setMetadataMessages((current) => ({
      ...current,
      [candidateId]: "Saving metadata...",
    }));

    try {
      const response = await fetch(
        `/api/videos/${selectedVideoId}/clips/${candidateId}/metadata`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: draft.title.trim(),
            description: draft.description.trim(),
            hashtags,
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not save metadata.");
      }

      const metadata = data as ClipMetadata;

      setClips((current) =>
        current.map((clip) =>
          clip.candidate_id === candidateId
            ? { ...clip, metadata }
            : clip
        )
      );

      setMetadataDrafts((current) => ({
        ...current,
        [candidateId]: {
          title: metadata.title,
          description: metadata.description,
          hashtags: metadata.hashtags.join(" "),
        },
      }));

      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: "Metadata saved successfully.",
      }));
    } catch (err) {
      setMetadataMessages((current) => ({
        ...current,
        [candidateId]:
          err instanceof Error ? err.message : "Could not save metadata.",
      }));
    } finally {
      setMetadataSavingId(null);
    }
  };

  const copyMetadata = async (
    candidateId: number,
    label: string,
    value: string
  ) => {
    try {
      await navigator.clipboard.writeText(value);

      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: `${label} copied to clipboard.`,
      }));
    } catch {
      setMetadataMessages((current) => ({
        ...current,
        [candidateId]: "Clipboard access failed. Please copy the text manually.",
      }));
    }
  };

  const submitVideoUrl = async () => {
    if (ingesting) return;

    setIngesting(true);
    setIngestError("");
    setPipelineStatus(null);

    try {
      const response = await fetch("/api/videos/ingest-url", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          source_url: sourceUrl.trim(),
          source_name: sourceName.trim(),
          commercial_rights_confirmed: rightsConfirmed,
        }),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        const detail = data.detail;

        const message =
          typeof detail === "string"
            ? detail
            : typeof detail?.message === "string"
              ? detail.message
              : "Could not import this video.";

        throw new Error(message);
      }

      const result = data as IngestVideoResponse;

      setPipelineStatus({
        job_id: result.job_id,
        video_id: result.video_id,
        status: result.status,
        current_stage: result.current_stage,
        progress_percent: result.progress_percent,
        error_message: null,
      });

      setActivePipeline({
        videoId: result.video_id,
        jobId: result.job_id,
      });

      setSourceUrl("");

      // Select the newly imported video.
      await loadVideos(result.video_id);
    } catch (err) {
      setIngestError(
        err instanceof Error ? err.message : "Could not import this video."
      );
    } finally {
      setIngesting(false);
    }
  };

  // Recover an existing pipeline when the dashboard opens or refreshes.
  // This checks existing jobs; it does NOT start a new pipeline.
  useEffect(() => {
    let cancelled = false;

    const initializeDashboard = async () => {
      try {
        const loadedVideos = await loadVideos();

        // Check the pipeline status of each video.
        const statuses = await Promise.all(
          loadedVideos.map(async (item) => {
            try {
              const response = await fetch(
                `/api/videos/${item.id}/pipeline/status`
              );

              if (!response.ok) {
                return null;
              }

              const status: PipelineStatusResponse =
                await response.json();

              if (
                status.status !== "pending" &&
                status.status !== "running"
              ) {
                return null;
              }

              return {
                videoId: item.id,
                jobId: status.job_id,
                status,
              };
            } catch {
              // A failed status request for one video should
              // not prevent recovery checks for other videos.
              return null;
            }
          })
        );

        if (cancelled) return;

        // Videos are returned newest first, so the first active
        // job is the newest active pipeline.
        const activeJob = statuses.find((item) => item !== null);

        if (activeJob) {
          setSelectedVideoId(activeJob.videoId);
          setPipelineStatus(activeJob.status);

          setActivePipeline({
            videoId: activeJob.videoId,
            jobId: activeJob.jobId,
          });
        }
      } catch (err) {
        if (cancelled) return;

        setError(
          err instanceof Error
            ? err.message
            : "Could not load video library."
        );

        setLoading(false);
      }
    };

    void initializeDashboard();

    return () => {
      cancelled = true;
    };
  }, [loadVideos]);

  useEffect(() => {
    if (selectedVideoId === null) return;

    setSelectedScenes([]);
    setCurrentScene(null);
    setOffset(0);
    setTotalScenes(0);

    loadScenes(selectedVideoId, 0);
  }, [selectedVideoId, loadScenes]);

  useEffect(() => {
    if (selectedVideoId === null) {
      setClips([]);
      return;
    }

    loadClips(selectedVideoId);
  }, [selectedVideoId, loadClips]);

  // Poll the recovered or newly created pipeline.
  useEffect(() => {
    if (activePipeline === null) return;

    let cancelled = false;
    let timeoutId: ReturnType<typeof window.setTimeout> | undefined;

    const pollPipelineStatus = async () => {
      try {
        const response = await fetch(
          `/api/videos/${activePipeline.videoId}/pipeline/status`
        );

        if (!response.ok) {
          throw new Error("Could not retrieve pipeline progress.");
        }

        const data: PipelineStatusResponse = await response.json();

        if (cancelled) return;

        setPipelineStatus(data);

        if (
          data.status === "completed" ||
          data.status === "completed_with_warnings"
        ) {
          setActivePipeline(null);

          // Refresh the processed video's library, scenes and clips.
          await Promise.all([
            loadVideos(activePipeline.videoId),
            loadScenes(activePipeline.videoId, 0),
            loadClips(activePipeline.videoId),
          ]);

          return;
        }

        if (data.status === "failed") {
          setActivePipeline(null);
          return;
        }

        // Continue polling while the pipeline is active.
        timeoutId = window.setTimeout(
          () => void pollPipelineStatus(),
          2000
        );
      } catch (err) {
        if (cancelled) return;

        setIngestError(
          err instanceof Error
            ? err.message
            : "Could not retrieve pipeline progress."
        );

        setActivePipeline(null);
      }
    };

    void pollPipelineStatus();

    return () => {
      cancelled = true;

      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [activePipeline, loadVideos, loadScenes, loadClips]);

  const selectScene = (scene: Scene) => {
    setCurrentScene(scene);

    if (videoRef.current) {
      videoRef.current.currentTime = scene.start_time;

      videoRef.current.play().catch(() => {
        // Playback can require direct user interaction in some browsers.
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
            <div className="breadcrumb">
              Workspace / Videos / Scene Browser
            </div>
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

        <section className="ingest-section">
          <div className="ingest-heading">
            <div>
              <div className="eyebrow">NEW SOURCE</div>
              <h3>Import a video</h3>
              <p>
                Add a YouTube video to your local studio and automatically
                generate review clips and vertical Shorts.
              </p>
            </div>

            <span className="video-tag">SOURCE UP TO 1440P</span>
          </div>

          <form
            className="ingest-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submitVideoUrl();
            }}
          >
            <label className="ingest-field">
              <span>YouTube video URL</span>
              <input
                type="url"
                value={sourceUrl}
                onChange={(event) => setSourceUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                maxLength={2048}
                required
                disabled={ingesting || activePipeline !== null}
              />
            </label>

            <label className="ingest-field">
              <span>Video name</span>
              <input
                type="text"
                value={sourceName}
                onChange={(event) => setSourceName(event.target.value)}
                placeholder="Give this video a name"
                maxLength={255}
                required
                disabled={ingesting || activePipeline !== null}
              />
            </label>

            <label className="rights-confirmation">
              <input
                type="checkbox"
                checked={rightsConfirmed}
                onChange={(event) => setRightsConfirmed(event.target.checked)}
                required
                disabled={ingesting || activePipeline !== null}
              />

              <span>
                I confirm that I have the necessary commercial rights or
                permissions to use this video.
              </span>
            </label>

            <button
              className="ingest-submit"
              type="submit"
              disabled={
                ingesting ||
                activePipeline !== null ||
                !sourceUrl.trim() ||
                !sourceName.trim() ||
                !rightsConfirmed
              }
            >
              {ingesting ? "Importing video..." : "Import and process video"}
            </button>
          </form>

          {ingesting && (
            <div className="ingest-message" role="status">
              Downloading the source and preparing your processing job.
              Larger videos may take some time to import.
            </div>
          )}

          {ingestError && (
            <div className="ingest-error" role="alert">
              {ingestError}
            </div>
          )}

          {pipelineStatus && (
            <div className="pipeline-progress" aria-live="polite">
              <div className="pipeline-progress-heading">
                <div>
                  <strong>
                    {pipelineStatus.status === "completed"
                      ? "Processing completed"
                      : pipelineStatus.status === "completed_with_warnings"
                        ? "Completed with warnings"
                        : pipelineStatus.status === "failed"
                          ? "Processing failed"
                          : "Video processing"}
                  </strong>

                  <span>
                    Job #{pipelineStatus.job_id} ·{" "}
                    {pipelineStatus.current_stage.replace(/_/g, " ")}
                  </span>
                </div>

                <strong className="pipeline-percent">
                  {pipelineStatus.progress_percent}%
                </strong>
              </div>

              <div
                className="progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pipelineStatus.progress_percent}
              >
                <span
                  style={{
                    width: `${Math.max(
                      0,
                      Math.min(100, pipelineStatus.progress_percent)
                    )}%`,
                  }}
                />
              </div>

              {pipelineStatus.status === "failed" &&
                pipelineStatus.error_message && (
                  <p className="pipeline-error">
                    {pipelineStatus.error_message}
                  </p>
                )}

              {(pipelineStatus.status === "completed" ||
                pipelineStatus.status === "completed_with_warnings") && (
                <p className="pipeline-success">
                  {pipelineStatus.status === "completed_with_warnings"
                    ? "Processing finished, but some stages reported warnings. Your available scenes and outputs have been refreshed below."
                    : "Your scenes and generated outputs have been refreshed below."}
                </p>
              )}
            </div>
          )}
        </section>

        <section className="video-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">YOUR VIDEO</div>
              <h3>{video?.original_filename || "Loading video..."}</h3>
              <p>Review your video and explore its detected scenes.</p>
            </div>

            <div className="video-controls">
              <label className="video-selector">
                <span>SELECT VIDEO</span>

                <select
                  value={selectedVideoId ?? ""}
                  onChange={(event) =>
                    setSelectedVideoId(Number(event.target.value))
                  }
                  disabled={videos.length === 0}
                >
                  {videos.map((item) => (
                    <option key={item.id} value={item.id}>
                      #{item.id} · {item.original_filename}
                    </option>
                  ))}
                </select>
              </label>

              <div className="video-tag">
                VIDEO #{selectedVideoId ?? "—"}
              </div>
            </div>
          </div>

          <div className="video-layout">
            <div className="player-card">
              <div className="player-frame">
                <video
                  ref={videoRef}
                  controls
                  preload="metadata"
                  src={
                    selectedVideoId !== null
                      ? `/api/videos/${selectedVideoId}/stream`
                      : undefined
                  }
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

        <section className="clips-section">
          <div className="section-heading">
            <div>
              <div className="eyebrow">YOUR GENERATED OUTPUTS</div>
              <h3>Generated Clips</h3>
              <p>
                Preview and download your review clips and finished outputs.
              </p>
            </div>

            <div className="video-tag">
              {clips.length} {clips.length === 1 ? "CANDIDATE" : "CANDIDATES"}
            </div>
          </div>

          {clipLoading ? (
            <div className="loading-state">Loading generated clips...</div>
          ) : clipError ? (
            <div className="loading-state">{clipError}</div>
          ) : clips.length === 0 ? (
            <div className="loading-state">
              No generated clips for this video yet. Generated outputs will
              appear here after the pipeline finishes.
            </div>
          ) : (
            <div className="clips-grid">
              {clips.map((clip) => {
                const output = clip.shorts ?? clip.full;

                const outputLabel = clip.shorts
                  ? "YouTube Shorts · 9:16"
                  : clip.full
                    ? "Full-screen output"
                    : "Output not generated";

                const metadataDraft = metadataDrafts[clip.candidate_id] ?? {
                  title: "",
                  description: "",
                  hashtags: "",
                };

                return (
                  <article className="clip-card" key={clip.candidate_id}>
                    <div className="clip-card-heading">
                      <strong>Candidate #{clip.candidate_id}</strong>
                      <span>{outputLabel}</span>
                    </div>

                    <div className="clip-pair">
                      {clip.review && (
                        <div className="clip-media">
                          <div className="clip-media-heading">
                            <strong>Review clip</strong>
                            <span>{formatSize(clip.review.size_bytes)}</span>
                          </div>

                          <div className="clip-video-frame">
                            <video
                              controls
                              preload="metadata"
                              src={clip.review.url}
                            />
                          </div>

                          <a
                            className="clip-download"
                            href={clip.review.url}
                            download={clip.review.filename}
                          >
                            Download review clip ↓
                          </a>
                        </div>
                      )}

                      {output && (
                        <div className="clip-media">
                          <div className="clip-media-heading">
                            <strong>
                              {clip.shorts ? "YouTube Shorts" : "Full-screen"}
                            </strong>

                            <span>{formatSize(output.size_bytes)}</span>
                          </div>

                          <div
                            className={`clip-video-frame ${
                              clip.shorts ? "vertical" : ""
                            }`}
                          >
                            <video
                              controls
                              preload="metadata"
                              src={output.url}
                            />
                          </div>

                          <a
                            className="clip-download"
                            href={output.url}
                            download={output.filename}
                          >
                            Download finished clip ↓
                          </a>
                        </div>
                      )}

                      {!output && (
                          <div className="clip-output-pending">
                            The finished output has not been generated yet.
                          </div>
                        )}
                      </div>

                      {clip.shorts && (
                        <div className="metadata-editor">
                          <div className="metadata-heading">
                            <div>
                              <strong>ChaosReel · YouTube Metadata</strong>
                              <span>
                                {clip.metadata?.status === "completed"
                                  ? "Saved metadata available"
                                  : "Generate metadata for this Short"}
                              </span>
                            </div>
                            <button
                              type="button"
                              className="metadata-generate"
                              disabled={metadataGeneratingId !== null}
                              onClick={() => generateClipMetadata(clip.candidate_id)}
                            >
                              {metadataGeneratingId === clip.candidate_id
                                ? "Generating..."
                                : clip.metadata
                                  ? "Regenerate with AI"
                                  : "Generate with AI"}
                            </button>
                          </div>

                          <label className="metadata-field">
                            Title
                            <input
                              value={metadataDraft.title}
                              maxLength={255}
                              placeholder="Generate or enter a Short title"
                              onChange={(event) =>
                                setMetadataDrafts((current) => ({
                                  ...current,
                                  [clip.candidate_id]: {
                                    ...metadataDraft,
                                    title: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <div className="metadata-copy-row">
                            <button
                              type="button"
                              disabled={!metadataDraft.title.trim()}
                              onClick={() =>
                                copyMetadata(clip.candidate_id, "Title", metadataDraft.title)
                              }
                            >
                              Copy title
                            </button>
                          </div>

                          <label className="metadata-field">
                            Description
                            <textarea
                              rows={4}
                              value={metadataDraft.description}
                              placeholder="Describe the actual moment in this Short"
                              onChange={(event) =>
                                setMetadataDrafts((current) => ({
                                  ...current,
                                  [clip.candidate_id]: {
                                    ...metadataDraft,
                                    description: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <div className="metadata-copy-row">
                            <button
                              type="button"
                              disabled={!metadataDraft.description.trim()}
                              onClick={() =>
                                copyMetadata(
                                  clip.candidate_id,
                                  "Description",
                                  metadataDraft.description
                                )
                              }
                            >
                              Copy description
                            </button>
                          </div>

                          <label className="metadata-field">
                            Hashtags
                            <input
                              value={metadataDraft.hashtags}
                              placeholder="ChaosReel GamingMoments Shorts"
                              onChange={(event) =>
                                setMetadataDrafts((current) => ({
                                  ...current,
                                  [clip.candidate_id]: {
                                    ...metadataDraft,
                                    hashtags: event.target.value,
                                  },
                                }))
                              }
                            />
                            <span>Separate 3–8 hashtags with spaces or commas.</span>
                          </label>

                          <div className="metadata-actions">
                            <button
                              type="button"
                              disabled={!metadataDraft.hashtags.trim()}
                              onClick={() =>
                                copyMetadata(
                                  clip.candidate_id,
                                  "Hashtags",
                                  metadataDraft.hashtags
                                    .split(/[\\s,]+/)
                                    .filter(Boolean)
                                    .map((tag) => tag.startsWith("#") ? tag : `#${tag}`)
                                    .join(" ")
                                )
                              }
                            >
                              Copy hashtags
                            </button>
                            <button
                              type="button"
                              className="metadata-save"
                              disabled={
                                metadataSavingId !== null ||
                                !metadataDraft.title.trim() ||
                                !metadataDraft.description.trim()
                              }
                              onClick={() => saveClipMetadata(clip.candidate_id)}
                            >
                              {metadataSavingId === clip.candidate_id
                                ? "Saving..."
                                : "Save changes"}
                            </button>
                          </div>

                          {metadataMessages[clip.candidate_id] && (
                            <p className="metadata-message" role="status">
                              {metadataMessages[clip.candidate_id]}
                            </p>
                          )}
                        </div>
                      )}

                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="scenes-section">
          <div className="scenes-heading">
            <div>
              <div className="eyebrow">VIDEO BREAKDOWN</div>
              <h3>Detected scenes</h3>
              <p>
                Choose a scene to preview it, or select multiple scenes.
              </p>
            </div>

            <div className="selection-count">
              <strong>{selectedScenes.length}</strong>
              <span>selected</span>
            </div>
          </div>

          <div className="scene-toolbar">
            <span>
              Showing {scenes.length ? offset + 1 : 0}–
              {Math.min(offset + scenes.length, totalScenes)} of {totalScenes}{" "}
              scenes
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
                      <span className="scene-number">
                        #{scene.scene_number}
                      </span>
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
                        <span>
                          {scene.transcript_segments.length} segments
                        </span>
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
              onClick={() =>
                selectedVideoId !== null &&
                loadScenes(
                  selectedVideoId,
                  Math.max(0, offset - PAGE_SIZE)
                )
              }
            >
              ← Previous
            </button>

            <span>
              Page <strong>{currentPage}</strong> of {totalPages}
            </span>

            <button
              disabled={currentPage >= totalPages || loading}
              onClick={() =>
                selectedVideoId !== null &&
                loadScenes(selectedVideoId, offset + PAGE_SIZE)
              }
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
