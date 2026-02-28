import { useState, useCallback } from 'react';
import {
  Layers, Video, Box, FolderOpen, Save, FilePlus,
} from 'lucide-react';
import { PipelineTab } from './components/PipelineTab';
import { VideoTab } from './components/VideoTab';
import { ViewerTab } from './components/ViewerTab';
import { useProject } from './stores/useProject';

type TabId = 'pipeline' | 'video' | 'viewer';

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'pipeline', label: 'Pipeline',      icon: <Layers size={16} /> },
  { id: 'video',    label: 'Video Preview', icon: <Video size={16} /> },
  { id: 'viewer',   label: '3D Viewer',     icon: <Box size={16} /> },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('pipeline');
  const { project, setVideo, updateSettings, runDemo, stopPipeline, resetProject, log } = useProject();

  const handleSaveProject = useCallback(() => {
    const blob = new Blob([JSON.stringify(project, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${project.name}.splatproj.json`;
    a.click();
    URL.revokeObjectURL(url);
    log('Project saved');
  }, [project, log]);

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center gap-2 px-4 py-2 bg-surface border-b border-border-subtle shrink-0">
        {/* Project actions */}
        <div className="flex items-center gap-1 mr-4">
          <HeaderButton icon={<FilePlus size={15} />} label="New" onClick={resetProject} />
          <HeaderButton icon={<FolderOpen size={15} />} label="Open" onClick={() => log('Open project (prototype)')} />
          <HeaderButton icon={<Save size={15} />} label="Save" onClick={handleSaveProject} />
        </div>

        {/* Divider */}
        <div className="w-px h-5 bg-border-subtle" />

        {/* Tab bar */}
        <nav className="flex items-center gap-1 ml-4">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200
                ${activeTab === tab.id
                  ? 'bg-accent/15 text-accent'
                  : 'text-text-muted hover:text-text hover:bg-surface-hover'}
              `}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Spacer + project name */}
        <div className="flex-1" />
        <span className="text-xs text-text-muted font-mono truncate max-w-60">
          {project.name}
          {project.isProcessing && (
            <span className="ml-2 inline-flex items-center gap-1 text-running">
              <span className="inline-block w-1.5 h-1.5 bg-running rounded-full animate-pulse" />
              Processing
            </span>
          )}
        </span>
      </header>

      {/* Tab content */}
      <main className="flex-1 min-h-0 relative">
        <div className={activeTab === 'pipeline' ? 'h-full' : 'hidden'}>
          <PipelineTab
            project={project}
            onVideoSelect={(file) => { setVideo(file); setActiveTab('video'); }}
            onSettingsChange={updateSettings}
            onStart={runDemo}
            onStop={stopPipeline}
            onReset={resetProject}
          />
        </div>
        <div className={activeTab === 'video' ? 'h-full' : 'hidden'}>
          <VideoTab videoUrl={project.videoUrl} isActiveTab={activeTab === 'video'} />
        </div>
        <div className={activeTab === 'viewer' ? 'h-full relative' : 'hidden'}>
          <ViewerTab plyUrl={project.plyUrl} />
        </div>
      </main>
    </div>
  );
}

function HeaderButton({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-muted hover:text-text hover:bg-surface-hover transition-colors"
      title={label}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
