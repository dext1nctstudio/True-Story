"use client";

/**
 * The drag and drop path.
 *
 * The only way into the pipeline before this was a raw multipart POST typed
 * by hand. Accepts fdx, fountain, pdf and plain text, same as the API.
 */

import { useCallback, useRef, useState } from "react";

const ACCEPT = ".fountain,.fdx,.pdf,.txt";

interface Props {
  onFile: (file: File) => void;
  uploading: boolean;
  error: string | null;
}

export function UploadZone({ onFile, uploading, error }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragOver(false);
      const file = event.dataTransfer.files[0];
      if (file) onFile(file);
    },
    [onFile],
  );

  return (
    <div
      className={`upload-zone ${dragOver ? "drag-over" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = "";
        }}
      />
      {uploading ? (
        <p>Uploading and starting the run…</p>
      ) : (
        <>
          <p className="upload-title">Drop a screenplay here, or click to browse.</p>
          <p className="upload-hint">Fountain, Final Draft, PDF or plain text.</p>
        </>
      )}
      {error && <p className="warning">{error}</p>}
    </div>
  );
}
