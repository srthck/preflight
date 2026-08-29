"use client";

import { useRef, useState } from "react";
import { Activity, FileArchive, GitCompare, ShieldCheck, UploadCloud, X } from "lucide-react";
import styles from "../page.module.css";
import { MAX_UPLOAD_BYTES } from "../../lib/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validateZip(chosen: File | null): { file: File | null; error: string } {
  if (!chosen) return { file: null, error: "" };
  if (!chosen.name.toLowerCase().endsWith(".zip")) {
    return { file: null, error: "Only .zip archives are accepted." };
  }
  if (chosen.size > MAX_UPLOAD_BYTES) {
    return {
      file: null,
      error: `Archive is ${formatBytes(chosen.size)}; the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`,
    };
  }
  return { file: chosen, error: "" };
}

function SinglePicker({
  label,
  hint,
  file,
  onPick,
  disabled,
}: {
  label: string;
  hint: string;
  file: File | null;
  onPick: (file: File | null) => void;
  disabled: boolean;
}) {
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const onChosen = (chosen: File | null) => {
    const result = validateZip(chosen);
    setError(result.error);
    onPick(result.file);
  };
  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept=".zip,application/zip"
        className="visuallyHidden"
        onChange={(e) => onChosen(e.target.files?.[0] ?? null)}
        aria-label={label}
      />
      {!file ? (
        <button
          type="button"
          className={styles.uploadDropzone}
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          <UploadCloud size={20} />
          <span>{label}</span>
          <small>{hint}</small>
        </button>
      ) : (
        <div className={styles.uploadReadyHead}>
          <FileArchive size={16} />
          <span>{file.name}</span>
          <small>{formatBytes(file.size)}</small>
          <button type="button" onClick={() => onChosen(null)} aria-label={`Remove ${label}`} disabled={disabled}>
            <X size={14} />
          </button>
        </div>
      )}
      {error && <p className={styles.errorInline}>{error}</p>}
    </div>
  );
}

// A controlled picker only — the actual upload request is owned by page.tsx
// so it can drive the same real-pipeline-stage sequence the scenario path
// uses. This component never talks to the network itself.
export function UploadPanel({
  loading,
  onAnalyze,
  onAnalyzeChange,
}: {
  loading: boolean;
  onAnalyze: (file: File) => void;
  onAnalyzeChange: (oldFile: File, newFile: File) => void;
}) {
  const [mode, setMode] = useState<"single" | "compare">("single");
  const [file, setFile] = useState<File | null>(null);
  const [oldFile, setOldFile] = useState<File | null>(null);
  const [newFile, setNewFile] = useState<File | null>(null);

  return (
    <div className={styles.uploadPanel}>
      <div className={styles.scenarioSwitch} role="group" aria-label="Choose analysis mode">
        <button
          type="button"
          className={`${styles.scenarioButton} ${mode === "single" ? styles.scenarioButtonActive : ""}`}
          onClick={() => setMode("single")}
          disabled={loading}
          aria-pressed={mode === "single"}
        >
          <UploadCloud size={13} /> Single project
        </button>
        <button
          type="button"
          className={`${styles.scenarioButton} ${mode === "compare" ? styles.scenarioButtonActive : ""}`}
          onClick={() => setMode("compare")}
          disabled={loading}
          aria-pressed={mode === "compare"}
        >
          <GitCompare size={13} /> Compare two versions
        </button>
      </div>

      {mode === "single" ? (
        <>
          <SinglePicker
            label="Drop a ZIP or choose a project archive"
            hint="Python · Kotlin · SQL · OpenAPI — analyzed without executing uploaded code"
            file={file}
            onPick={setFile}
            disabled={loading}
          />
          {file && (
            <button type="button" className={styles.primary} onClick={() => onAnalyze(file)} disabled={loading}>
              {loading ? <Activity className={styles.spin} size={16} /> : <ShieldCheck size={16} />}
              {loading ? "Analyzing project…" : "Analyze project"}
            </button>
          )}
        </>
      ) : (
        <>
          <p className={styles.uploadCompareHint}>
            PreFlight&rsquo;s real unit of analysis is the change, not the file. Upload the currently-deployed
            repository and the proposed one — PreFlight diffs them by content and analyzes only what
            actually changed.
          </p>
          <SinglePicker
            label="OLD — currently deployed"
            hint="What is running in production right now"
            file={oldFile}
            onPick={setOldFile}
            disabled={loading}
          />
          <SinglePicker
            label="NEW — proposed"
            hint="What you want to ship"
            file={newFile}
            onPick={setNewFile}
            disabled={loading}
          />
          {oldFile && newFile && (
            <button
              type="button"
              className={styles.primary}
              onClick={() => onAnalyzeChange(oldFile, newFile)}
              disabled={loading}
            >
              {loading ? <Activity className={styles.spin} size={16} /> : <ShieldCheck size={16} />}
              {loading ? "Analyzing change…" : "Analyze change"}
            </button>
          )}
        </>
      )}
    </div>
  );
}
