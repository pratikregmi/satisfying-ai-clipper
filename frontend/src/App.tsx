
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

type PipelineStageDetail = {
  status?: string;
  error?: string;
  started_at?: string;
  completed_at?: string;
  updated_at?: string;
  [key: string]: unknown;
};

type PipelineStatusResponse = {
  job_id: number;
  video_id: number;
  status: string;
  current_stage: string;
  progress_percent: number;
  stage_details?: Record<string, PipelineStageDetail>;
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

const PIPELINE_STAGES = [
  {
    key: "transcription",
    label: "Transcribing audio",
    description: "Converting spoken audio into searchable text.",
  },
  {
    key: "scene_detection",
    label: "Detecting scenes",
    description: "Finding scene changes and meaningful visual sections.",
  },
  {
    key: "thumbnail_generation",
    label: "Creating thumbnails",
    description: "Preparing preview images for detected scenes.",
  },
  {
    key: "scene_transcript_matching",
    label: "Matching scenes with speech",
    description: "Connecting scene timings with the transcript.",
  },
  {
    key: "visual_analysis",
    label: "Analyzing the visuals",
    description: "Reviewing scene content and visual context.",
  },
  {
    key: "moment_discovery",
    label: "Discovering interesting moments",
    description: "Finding promising moments that may work as Shorts.",
  },
  {
    key: "preliminary_ranking",
    label: "Ranking candidate moments",
    description: "Prioritizing the strongest moments for evaluation.",
  },
  {
    key: "ai_evaluation",
    label: "Evaluating moments",
    description: "Scoring and reviewing shortlisted candidates.",
  },
  {
    key: "final_ranking",
    label: "Selecting the best moments",
    description: "Choosing the final moments for clip generation.",
  },
  {
    key: "clip_generation",
    label: "Generating clips",
    description: "Creating the selected video clips.",
  },
  {
    key: "output_generation",
    label: "Preparing Shorts",
    description: "Producing the final vertical video outputs.",
  },
  {
    key: "results_export",
    label: "Saving results",
    description: "Exporting the completed processing results.",
  },
];

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
  const [activeSection, setActiveSection] = useState("new-project");
  const [selectedShortsVideoId, setSelectedShortsVideoId] = useState<number | null>(null);

  const [videos, setVideos] = useState<Video[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null);
  const shortsSourceVideo =
    videos.find((item) => item.id === selectedShortsVideoId) ?? null;

  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScenes, setSelectedScenes] = useState<number[]>([]);
  const [currentScene, setCurrentScene] = useState<Scene | null>(null);
  const [offset, setOffset] = useState(0);
  const [totalScenes, setTotalScenes] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [clips, setClips] = useState<GeneratedClip[]>([]);
  const [clipsByVideo, setClipsByVideo] = useState<Record<number, GeneratedClip[]>>({});
  const [clipGroupsLoading, setClipGroupsLoading] = useState(false);
  const [, setClipLoading] = useState(false);
  const [, setClipError] = useState("");
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

  const generateClipMetadata = async (videoId: number, candidateId: number) => {
    if (metadataGeneratingId !== null) return;

    setMetadataGeneratingId(candidateId);
    setMetadataMessages((current) => ({
      ...current,
      [candidateId]: "Generating metadata with AI...",
    }));

    try {
      const response = await fetch(
        `/api/videos/${videoId}/clips/${candidateId}/metadata/generate`,
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
      setClipsByVideo((current) => ({
        ...current,
        [videoId]: (current[videoId] ?? []).map((clip) =>
          clip.candidate_id === candidateId
            ? { ...clip, metadata }
            : clip
        ),
      }));

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

  const saveClipMetadata = async (videoId: number, candidateId: number) => {
    if (metadataSavingId !== null) return;

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
        `/api/videos/${videoId}/clips/${candidateId}/metadata`,
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
      setClipsByVideo((current) => ({
        ...current,
        [videoId]: (current[videoId] ?? []).map((clip) =>
          clip.candidate_id === candidateId
            ? { ...clip, metadata }
            : clip
        ),
      }));

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


  // Load generated clips for every uploaded video for the My Shorts collection.
  useEffect(() => {
    let cancelled = false;

    const loadAllVideoClips = async () => {
      if (videos.length === 0) {
        setClipsByVideo({});
        setClipGroupsLoading(false);
        return;
      }

      setClipGroupsLoading(true);

      try {
        const entries = await Promise.all(
          videos.map(async (item) => {
            try {
              const response = await fetch(`/api/videos/${item.id}/clips`);

              if (!response.ok) {
                throw new Error("Could not load clips.");
              }

              const data: GeneratedClipsResponse = await response.json();
              return [item.id, data.clips ?? []] as const;
            } catch {
              return [item.id, []] as const;
            }
          })
        );

        if (cancelled) return;

        setClipsByVideo(Object.fromEntries(entries));

        const loadedDrafts = Object.fromEntries(
          entries.flatMap(([, videoClips]) =>
            videoClips.map((clip) => [
              clip.candidate_id,
              {
                title: clip.metadata?.title ?? "",
                description: clip.metadata?.description ?? "",
                hashtags: clip.metadata?.hashtags.join(" ") ?? "",
              },
            ])
          )
        );

        setMetadataDrafts((current) => ({
          ...current,
          ...loadedDrafts,
        }));
      } finally {
        if (!cancelled) {
          setClipGroupsLoading(false);
        }
      }
    };

    void loadAllVideoClips();

    return () => {
      cancelled = true;
    };
  }, [videos]);

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

  const pageDetails: Record<string, { title: string; breadcrumb: string }> = {
    "new-project": { title: "Home", breadcrumb: "Workspace / Home" },
    "video-library": { title: "Create", breadcrumb: "Workspace / Create" },
    "original-content": { title: "Original Content", breadcrumb: "Workspace / Original Content" },
    "my-shorts": { title: "My Shorts", breadcrumb: "Workspace / My Shorts" },
    "scene-library": { title: "Scene Library", breadcrumb: "Workspace / Scene Library" },
  };

  const currentPageDetails = pageDetails[activeSection] ?? pageDetails["new-project"];

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

          <a className={activeSection === "new-project" ? "nav-item active" : "nav-item"} href="#new-project" onClick={() => setActiveSection("new-project")}>
            <span>⌂</span> Home
          </a>

          <a className={activeSection === "video-library" ? "nav-item active" : "nav-item"} href="#new-project" onClick={() => setActiveSection("video-library")}>
            <span>✧</span> Create
          </a>

          <a className={activeSection === "original-content" ? "nav-item active" : "nav-item"} href="#original-content" onClick={() => setActiveSection("original-content")}>
            <span>▤</span> Original Content
          </a>

          <a className={activeSection === "my-shorts" ? "nav-item active" : "nav-item"} href="#my-shorts" onClick={() => {
            setSelectedShortsVideoId(null);
            setActiveSection("my-shorts");
          }}>
            <span>▣</span> My Shorts
          </a>

          <a className={activeSection === "scene-library" ? "nav-item active" : "nav-item"} href="#scene-library" onClick={() => setActiveSection("scene-library")}>
            <span>▦</span> Scene Library
          </a>
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
              {currentPageDetails.breadcrumb}
            </div>
            <h2>{currentPageDetails.title}</h2>
          </div>

          <div className="topbar-right">
            <span className="connection">
              <span className="status-dot" /> Backend connected
            </span>
            <div className="avatar">SA</div>
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        {activeSection === "new-project" && (
          <section className="dashboard-welcome">
            <div className="eyebrow">YOUR CREATIVE WORKSPACE</div>
            <h3>Turn your videos into engaging Shorts.</h3>
            <p>
              Import a YouTube video, let your local studio analyze it,
              and review your generated clips and vertical videos.
            </p>

            <div className="dashboard-actions">
              <a
                href="#new-project"
                className="welcome-primary"
                onClick={() => setActiveSection("video-library")}
              >
                Import a video <span>→</span>
              </a>
              <a
                href="#original-content"
                className="welcome-secondary"
                onClick={() => setActiveSection("original-content")}
              >
                Browse video library
              </a>
            </div>

            <div className="dashboard-stats">
              <div className="dashboard-stat">
                <strong>{videos.length.toLocaleString()}</strong>
                <span>Imported videos</span>
              </div>
              <div className="dashboard-stat">
                <strong>{totalScenes.toLocaleString()}</strong>
                <span>Scenes in selected video</span>
              </div>
              <div className="dashboard-stat">
                <strong>{clips.length.toLocaleString()}</strong>
                <span>Clip candidates</span>
              </div>
            </div>
          </section>
        )}

        {activeSection === "new-project" && (
          <section className="home-library" id="home-video-library">
            <div className="section-heading">
              <div>
                <div className="eyebrow">YOUR COLLECTION</div>
                <h3>Your videos</h3>
                <p>Select a video to continue working on it.</p>
              </div>
              <span className="video-tag">
                {videos.length} {videos.length === 1 ? "VIDEO" : "VIDEOS"}
              </span>
            </div>

            {loading && videos.length === 0 ? (
              <div className="loading-state">Loading your video collection...</div>
            ) : videos.length === 0 ? (
              <div className="home-library-empty">
                <div className="home-library-empty-icon">＋</div>
                <strong>Your video collection starts here</strong>
                <p>Import a video to begin creating clips and Shorts.</p>
                <a
                  href="#new-project"
                  onClick={() => setActiveSection("video-library")}
                >
                  Import your first video →
                </a>
              </div>
            ) : (
              <div className="home-video-grid">
                {videos.map((item) => (
                  <article className="home-video-card" key={item.id}>
                    <div className="home-video-art">
                      <img
                        className="home-video-thumbnail"
                        src={`/api/videos/${item.id}/thumbnail`}
                        alt=""
                        loading="lazy"
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      />
                      <span className="home-video-number">
                        VIDEO #{item.id}
                      </span>
                      <span className="home-video-play">▶</span>
                      <span className="home-video-duration">
                        {formatTime(item.duration)}
                      </span>
                    </div>

                    <div className="home-video-details">
                      <h4 title={item.original_filename}>
                        {item.original_filename}
                      </h4>
                      <div className="home-video-meta">
                        <span>{item.width} × {item.height}</span>
                        <span>{formatSize(item.file_size)}</span>
                      </div>
                      <button
                        type="button"
                        className="home-video-open"
                        onClick={() => {
                          setSelectedVideoId(item.id);
                          setActiveSection("scene-library");
                        }}
                      >
                        Open video <span>→</span>
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {activeSection === "video-library" && (
          <>
        <section className="ingest-section" id="new-project">
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
                      ? "Your video is ready"
                      : pipelineStatus.status === "completed_with_warnings"
                        ? "Processing finished with warnings"
                        : pipelineStatus.status === "failed"
                          ? "Processing needs attention"
                          : "Your video is being processed"}
                  </strong>
                  <span>
                    Job #{pipelineStatus.job_id} ·{" "}
                    {pipelineStatus.current_stage === "completed"
                      ? "All steps finished"
                      : pipelineStatus.current_stage.replace(/_/g, " ")}
                  </span>
                </div>
                <strong className="pipeline-percent">
                  {pipelineStatus.progress_percent}%
                </strong>
              </div>

              <div
                className="progress-track"
                role="progressbar"
                aria-label="Video processing progress"
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

              <div className="pipeline-timeline">
                <div className="pipeline-timeline-heading">
                  <div>
                    <strong>Processing activity</strong>
                    <span>Live updates from your video processing job</span>
                  </div>
                  <span>
                    {PIPELINE_STAGES.filter((stage) => {
                      const state =
                        pipelineStatus.stage_details?.[stage.key]?.status;
                      return [
                        "completed",
                        "completed_with_warnings",
                        "skipped",
                        "failed",
                      ].includes(state ?? "");
                    }).length}{" "}
                    / {PIPELINE_STAGES.length} steps finished
                  </span>
                </div>

                <div className="pipeline-stage-list">
                  <div className="pipeline-stage is-completed">
                    <span className="pipeline-stage-marker">✓</span>
                    <div className="pipeline-stage-copy">
                      <strong>Video imported</strong>
                      <span>
                        The source video was downloaded and added to your library.
                      </span>
                    </div>
                    <span className="pipeline-stage-state">Complete</span>
                  </div>

                  {PIPELINE_STAGES.map((stage) => {
                    const detail =
                      pipelineStatus.stage_details?.[stage.key];
                    const recordedStatus = detail?.status;
                    const isTerminal = [
                      "completed",
                      "completed_with_warnings",
                    ].includes(pipelineStatus.status);

                    const stageStatus =
                      recordedStatus ||
                      (pipelineStatus.current_stage === stage.key &&
                      ["pending", "running"].includes(pipelineStatus.status)
                        ? "running"
                        : "pending");

                    const stateLabel =
                      stageStatus === "completed"
                        ? "Complete"
                        : stageStatus === "completed_with_warnings"
                          ? "Warnings"
                          : stageStatus === "skipped"
                            ? "Skipped"
                            : stageStatus === "failed"
                              ? "Failed"
                              : stageStatus === "running"
                                ? "In progress"
                                : isTerminal
                                  ? "Not run"
                                  : "Waiting";

                    const marker =
                      stageStatus === "completed" ||
                      stageStatus === "completed_with_warnings" ||
                      stageStatus === "skipped"
                        ? "✓"
                        : stageStatus === "failed"
                          ? "!"
                          : stageStatus === "running"
                            ? "•"
                            : "·";

                    return (
                      <div
                        className={`pipeline-stage pipeline-stage-${stageStatus}`}
                        key={stage.key}
                      >
                        <span className="pipeline-stage-marker">{marker}</span>
                        <div className="pipeline-stage-copy">
                          <strong>{stage.label}</strong>
                          <span>{stage.description}</span>
                          {detail?.error && (
                            <span className="pipeline-stage-error">
                              {detail.error}
                            </span>
                          )}
                          {detail?.updated_at && (
                            <span className="pipeline-stage-time">
                              Updated{" "}
                              {new Date(detail.updated_at).toLocaleTimeString(
                                [],
                                { hour: "2-digit", minute: "2-digit" }
                              )}
                            </span>
                          )}
                        </div>
                        <span className="pipeline-stage-state">
                          {stateLabel}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {pipelineStatus.status === "failed" &&
                pipelineStatus.error_message && (
                  <p className="pipeline-error">
                    {pipelineStatus.error_message}
                  </p>
                )}

              {pipelineStatus.status === "completed" && (
                <p className="pipeline-success">
                  Processing is complete. Your scenes and generated Shorts are ready to review.
                </p>
              )}

              {pipelineStatus.status === "completed_with_warnings" && (
                <p className="pipeline-success">
                  Processing finished. Some steps reported warnings; review the activity above and check your available results.
                </p>
              )}
            </div>
          )}
        </section>



          </>
        )}

        {activeSection === "original-content" && (
          <section className="home-library" id="original-content">
            <div className="section-heading">
              <div>
                <div className="eyebrow">YOUR SOURCE LIBRARY</div>
                <h3>Original Content</h3>
                <p>All your imported original videos, organized in one place.</p>
              </div>
              <span className="video-tag">
                {videos.length} {videos.length === 1 ? "VIDEO" : "VIDEOS"}
              </span>
            </div>

            {loading && videos.length === 0 ? (
              <div className="loading-state">Loading original videos...</div>
            ) : videos.length === 0 ? (
              <div className="home-library-empty">
                <div className="home-library-empty-icon">＋</div>
                <strong>No original videos yet</strong>
                <p>Import a video to build your source library.</p>
                <button
                  type="button"
                  className="home-video-open"
                  onClick={() => setActiveSection("video-library")}
                >
                  Import a video →
                </button>
              </div>
            ) : (
              <div className="home-video-grid">
                {videos.map((item) => (
                  <article className="home-video-card" key={item.id}>
                    <div className="home-video-art">
                      <img
                        className="home-video-thumbnail"
                        src={`/api/videos/${item.id}/thumbnail`}
                        alt=""
                        loading="lazy"
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      />
                      <span className="home-video-number">VIDEO #{item.id}</span>
                      <span className="home-video-play">▶</span>
                      <span className="home-video-duration">{formatTime(item.duration)}</span>
                    </div>
                    <div className="home-video-details">
                      <h4 title={item.original_filename}>{item.original_filename}</h4>
                      <div className="home-video-meta">
                        <span>{item.width} × {item.height}</span>
                        <span>{formatSize(item.file_size)}</span>
                      </div>
                      <button
                        type="button"
                        className="home-video-open"
                        onClick={() => {
                          setSelectedVideoId(item.id);
                          setActiveSection("scene-library");
                        }}
                      >
                        Open original video <span>→</span>
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {activeSection === "my-shorts" && (
        <section className="clips-section" id="my-shorts">
          <div className="section-heading">
            <div>
              <div className="eyebrow">YOUR GENERATED OUTPUTS</div>
              <h3>{shortsSourceVideo ? shortsSourceVideo.original_filename : "My Shorts"}</h3>
              <p>
                {shortsSourceVideo
                  ? "Original video and all Shorts generated from this source."
                  : "Choose an original video to view its generated Shorts."}
              </p>
            </div>

            {shortsSourceVideo && (
              <button
                type="button"
                className="home-video-open"
                onClick={() => setSelectedShortsVideoId(null)}
              >
                ← Back to My Shorts
              </button>
            )}

            <div className="video-tag">
              {videos.reduce(
                (total, item) => total + (clipsByVideo[item.id]?.length ?? 0),
                0
              )} GENERATED CLIPS
            </div>
          </div>

          {clipGroupsLoading ? (
            <div className="loading-state">Loading your Shorts collection...</div>
          ) : videos.length === 0 ? (
            <div className="loading-state">
              No uploaded videos yet. Import a video to start creating Shorts.
            </div>
          ) : selectedShortsVideoId === null ? (
            <div className="home-video-grid">
              {videos.map((item) => {
                const sourceClips = clipsByVideo[item.id] ?? [];

                return (
                  <article className="home-video-card" key={item.id}>
                    <div className="home-video-art">
                      <img
                        className="home-video-thumbnail"
                        src={`/api/videos/${item.id}/thumbnail`}
                        alt=""
                        loading="lazy"
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      />
                      <span className="home-video-number">SOURCE VIDEO #{item.id}</span>
                      <span className="home-video-play">▶</span>
                      <span className="home-video-duration">{formatTime(item.duration)}</span>
                    </div>
                    <div className="home-video-details">
                      <h4 title={item.original_filename}>{item.original_filename}</h4>
                      <div className="home-video-meta">
                        <span>{sourceClips.length} generated {sourceClips.length === 1 ? "Short" : "Shorts"}</span>
                        <span>{formatSize(item.file_size)}</span>
                      </div>
                      <button
                        type="button"
                        className="home-video-open"
                        onClick={() => setSelectedShortsVideoId(item.id)}
                      >
                        Open this video's Shorts <span>→</span>
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <>
              {shortsSourceVideo && (
                <div className="shorts-source-player">
                  <div className="eyebrow">ORIGINAL SOURCE VIDEO</div>
                  <div className="player-card">
                    <div className="player-frame">
                      <video
                        controls
                        preload="metadata"
                        src={`/api/videos/${shortsSourceVideo.id}/stream`}
                      />
                    </div>
                    <div className="player-footer">
                      <div>
                        <strong>{shortsSourceVideo.original_filename}</strong>
                        <span>
                          {formatTime(shortsSourceVideo.duration)} ·{" "}
                          {shortsSourceVideo.width} × {shortsSourceVideo.height} ·{" "}
                          {formatSize(shortsSourceVideo.file_size)}
                        </span>
                      </div>
                      <span className="quality-tag">ORIGINAL</span>
                    </div>
                  </div>
                </div>
              )}

              <div className="shorts-video-groups">
              {videos.filter((item) => item.id === selectedShortsVideoId).map((sourceVideo) => {
                const sourceClips = clipsByVideo[sourceVideo.id] ?? [];

                return (
                  <section className="shorts-video-group" key={sourceVideo.id}>
                    <div className="shorts-video-group-heading">
                      <div>
                        <div className="eyebrow">
                          SOURCE VIDEO · VIDEO #{sourceVideo.id}
                        </div>
                        <h4>{sourceVideo.original_filename}</h4>
                        <p>
                          {formatTime(sourceVideo.duration)} ·{" "}
                          {sourceVideo.width} × {sourceVideo.height} ·{" "}
                          {formatSize(sourceVideo.file_size)}
                        </p>
                      </div>
                      <span className="video-tag">
                        {sourceClips.length}{" "}
                        {sourceClips.length === 1 ? "CLIP" : "CLIPS"}
                      </span>
                    </div>

                    {sourceClips.length === 0 ? (
                      <div className="loading-state">
                        No generated clips from this video yet.
                      </div>
                    ) : (
                      <div className="clips-grid">
                        {sourceClips.map((clip) => {
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
                              onClick={() => generateClipMetadata(sourceVideo.id, clip.candidate_id)}
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
                              onClick={() => saveClipMetadata(sourceVideo.id, clip.candidate_id)}
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
                );
              })}
              </div>
            </>
          )}
        </section>
        )}

        {activeSection === "scene-library" && (
        <section className="scenes-section" id="scene-library">
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
        )}

        <footer className="footer">
          <span>SatisfyingAI · Local AI Video Studio</span>
          <span>Built for private, local-first video workflows.</span>
        </footer>
      </section>
    </main>
  );
}

export default App;
