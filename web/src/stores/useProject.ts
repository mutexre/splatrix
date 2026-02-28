import { useState, useCallback } from 'react';
import type { ProjectState, StageStatus, ProjectSettings } from '../types';

const DEFAULT_STAGES = [
  { key: 'frames', label: 'Frame Extraction', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
  { key: 'features', label: 'Feature Extraction', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
  { key: 'matching', label: 'Feature Matching', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
  { key: 'reconstruction', label: 'Sparse Reconstruction', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
  { key: 'training', label: 'Training (Splatfacto)', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
  { key: 'export', label: 'Export PLY', status: 'pending' as StageStatus, progress: 0, detail: '', count: '' },
];

const DEFAULT_SETTINGS: ProjectSettings = {
  maxFrames: 300,
  trainingIterations: 30000,
  reconstructionMethod: 'nerfstudio',
};

export function useProject() {
  const [project, setProject] = useState<ProjectState>({
    name: 'Untitled Project',
    videoPath: null,
    videoUrl: null,
    plyUrl: null,
    settings: { ...DEFAULT_SETTINGS },
    stages: DEFAULT_STAGES.map(s => ({ ...s })),
    isProcessing: false,
    logs: [],
  });

  const log = useCallback((message: string) => {
    setProject(prev => ({
      ...prev,
      logs: [...prev.logs, `[${new Date().toLocaleTimeString()}] ${message}`],
    }));
  }, []);

  const setVideo = useCallback((file: File) => {
    const url = URL.createObjectURL(file);
    setProject(prev => {
      if (prev.videoUrl) URL.revokeObjectURL(prev.videoUrl);
      return { ...prev, videoPath: file.name, videoUrl: url, name: file.name.replace(/\.[^.]+$/, '') };
    });
  }, []);

  const updateSettings = useCallback((patch: Partial<ProjectSettings>) => {
    setProject(prev => ({ ...prev, settings: { ...prev.settings, ...patch } }));
  }, []);

  const updateStage = useCallback((key: string, patch: Partial<ProjectState['stages'][0]>) => {
    setProject(prev => ({
      ...prev,
      stages: prev.stages.map(s => s.key === key ? { ...s, ...patch } : s),
    }));
  }, []);

  const startPipeline = useCallback(() => {
    setProject(prev => ({
      ...prev,
      isProcessing: true,
      stages: DEFAULT_STAGES.map(s => ({ ...s })),
      logs: [...prev.logs, `[${new Date().toLocaleTimeString()}] Pipeline started`],
    }));
  }, []);

  const stopPipeline = useCallback(() => {
    setProject(prev => ({
      ...prev,
      isProcessing: false,
      stages: prev.stages.map(s =>
        s.status === 'running' ? { ...s, status: 'cancelled' as StageStatus, detail: 'Cancelled' } : s
      ),
    }));
  }, []);

  // Simulate pipeline for prototype demo
  const runDemo = useCallback(() => {
    startPipeline();
    const stages = DEFAULT_STAGES.map(s => s.key);
    let stageIdx = 0;

    const advanceStage = () => {
      if (stageIdx >= stages.length) {
        setProject(prev => ({ ...prev, isProcessing: false }));
        log('Pipeline complete!');
        return;
      }

      const key = stages[stageIdx];
      updateStage(key, { status: 'running', progress: 0, detail: 'Processing...' });
      log(`Stage: ${DEFAULT_STAGES[stageIdx].label} started`);

      let progress = 0;
      const interval = setInterval(() => {
        progress += Math.random() * 15 + 5;
        if (progress >= 100) {
          progress = 100;
          clearInterval(interval);
          updateStage(key, { status: 'completed', progress: 100, detail: 'Complete' });
          log(`Stage: ${DEFAULT_STAGES[stageIdx].label} completed`);
          stageIdx++;
          setTimeout(advanceStage, 300);
        } else {
          updateStage(key, { progress: Math.round(progress), detail: `${Math.round(progress)}%` });
        }
      }, 400);
    };

    advanceStage();
  }, [startPipeline, updateStage, log]);

  const resetProject = useCallback(() => {
    setProject(prev => ({
      ...prev,
      stages: DEFAULT_STAGES.map(s => ({ ...s })),
      isProcessing: false,
      logs: [],
    }));
  }, []);

  return { project, setVideo, updateSettings, updateStage, startPipeline, stopPipeline, runDemo, resetProject, log };
}
