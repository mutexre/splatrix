export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface PipelineStage {
  key: string;
  label: string;
  status: StageStatus;
  progress: number; // 0-100
  detail: string;
  count?: string; // e.g. "31/300"
}

export interface ProjectSettings {
  maxFrames: number;
  trainingIterations: number;
  reconstructionMethod: 'nerfstudio' | 'colmap' | 'mock';
}

export interface ProjectState {
  name: string;
  videoPath: string | null;
  videoUrl: string | null; // Object URL for preview
  plyUrl: string | null;   // Object URL for 3D viewer
  settings: ProjectSettings;
  stages: PipelineStage[];
  isProcessing: boolean;
  logs: string[];
}
