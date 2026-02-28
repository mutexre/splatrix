import { Upload, Play, Square, RotateCcw, Settings2, FolderOpen } from 'lucide-react';
import { useRef, type ChangeEvent } from 'react';
import { StageIndicator } from './StageIndicator';
import type { ProjectState, ProjectSettings } from '../types';

interface Props {
  project: ProjectState;
  onVideoSelect: (file: File) => void;
  onSettingsChange: (patch: Partial<ProjectSettings>) => void;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
}

export function PipelineTab({ project, onVideoSelect, onSettingsChange, onStart, onStop, onReset }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onVideoSelect(file);
  };

  return (
    <div className="flex flex-col h-full gap-4 p-4 overflow-y-auto">
      {/* Video Input */}
      <Section title="Video Input" icon={<Upload size={16} />}>
        <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={handleFileChange} />
        <div className="flex items-center gap-3">
          <button
            onClick={() => fileRef.current?.click()}
            disabled={project.isProcessing}
            className="btn-secondary"
          >
            <FolderOpen size={14} /> Select Video
          </button>
          <span className="text-sm text-text-muted truncate flex-1">
            {project.videoPath || 'No video selected'}
          </span>
        </div>
      </Section>

      {/* Settings */}
      <Section title="Processing Options" icon={<Settings2 size={16} />}>
        <div className="grid grid-cols-2 gap-3">
          <SettingField label="Max Frames">
            <input
              type="number"
              min={0} max={10000} step={10}
              value={project.settings.maxFrames}
              onChange={e => onSettingsChange({ maxFrames: +e.target.value })}
              disabled={project.isProcessing}
              className="input-field"
            />
          </SettingField>
          <SettingField label="Training Iterations">
            <input
              type="number"
              min={1000} max={100000} step={5000}
              value={project.settings.trainingIterations}
              onChange={e => onSettingsChange({ trainingIterations: +e.target.value })}
              disabled={project.isProcessing}
              className="input-field"
            />
          </SettingField>
          <SettingField label="Method" className="col-span-2">
            <select
              value={project.settings.reconstructionMethod}
              onChange={e => onSettingsChange({ reconstructionMethod: e.target.value as ProjectSettings['reconstructionMethod'] })}
              disabled={project.isProcessing}
              className="input-field"
            >
              <option value="nerfstudio">Nerfstudio (GPU Required)</option>
              <option value="colmap">COLMAP Only</option>
              <option value="mock">Mock (Test)</option>
            </select>
          </SettingField>
        </div>
      </Section>

      {/* Pipeline Stages */}
      <Section title="Pipeline Progress">
        <div className="space-y-2">
          {project.stages.map(stage => (
            <StageIndicator key={stage.key} stage={stage} />
          ))}
        </div>
      </Section>

      {/* Controls */}
      <div className="flex gap-2">
        <button
          onClick={onStart}
          disabled={!project.videoPath || project.isProcessing}
          className="btn-primary flex-1"
        >
          <Play size={14} /> Start Conversion
        </button>
        <button
          onClick={onStop}
          disabled={!project.isProcessing}
          className="btn-danger"
        >
          <Square size={14} /> Cancel
        </button>
        <button onClick={onReset} disabled={project.isProcessing} className="btn-secondary">
          <RotateCcw size={14} />
        </button>
      </div>

      {/* Log */}
      <Section title="Log" className="flex-1 min-h-0">
        <div className="h-48 overflow-y-auto rounded-lg bg-bg p-3 font-mono text-xs text-text-muted space-y-0.5">
          {project.logs.length === 0
            ? <span className="opacity-50">Ready</span>
            : project.logs.map((l, i) => <div key={i}>{l}</div>)}
        </div>
      </Section>
    </div>
  );
}

function Section({ title, icon, children, className = '' }: {
  title: string; icon?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={`rounded-xl border border-border-subtle bg-surface p-4 ${className}`}>
      <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
        {icon} {title}
      </h3>
      {children}
    </div>
  );
}

function SettingField({ label, children, className = '' }: {
  label: string; children: React.ReactNode; className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 ${className}`}>
      <span className="text-xs text-text-muted">{label}</span>
      {children}
    </label>
  );
}
