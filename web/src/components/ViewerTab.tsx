import { Suspense, useRef, useEffect } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Grid, Environment } from '@react-three/drei';
import * as THREE from 'three';
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js';

function PointCloudModel({ url }: { url: string }) {
  const ref = useRef<THREE.Points>(null);
  const { camera } = useThree();

  useEffect(() => {
    const loader = new PLYLoader();
    loader.load(url, (geometry) => {
      geometry.computeVertexNormals();
      geometry.computeBoundingBox();

      if (ref.current) {
        ref.current.geometry = geometry;

        // Center
        const center = new THREE.Vector3();
        geometry.boundingBox!.getCenter(center);
        ref.current.position.set(-center.x, -center.y, -center.z);

        // Fit camera
        const size = new THREE.Vector3();
        geometry.boundingBox!.getSize(size);
        const maxDim = Math.max(size.x, size.y, size.z);
        camera.position.set(maxDim, maxDim * 0.5, maxDim);
        (camera as THREE.PerspectiveCamera).lookAt(0, 0, 0);
      }
    });
  }, [url, camera]);

  return (
    <points ref={ref}>
      <bufferGeometry />
      <pointsMaterial size={0.02} vertexColors sizeAttenuation />
    </points>
  );
}

interface Props {
  plyUrl: string | null;
}

export function ViewerTab({ plyUrl }: Props) {
  if (!plyUrl) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <div className="text-center">
          <div className="text-4xl mb-3 opacity-30">🔮</div>
          <p>No PLY loaded</p>
          <p className="text-xs mt-1 opacity-60">Run the pipeline or open a project to view splats</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <Canvas
        camera={{ position: [5, 3, 5], fov: 60 }}
        gl={{ antialias: true }}
        style={{ background: '#0a0a0f' }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[10, 10, 10]} intensity={0.6} />
        <Suspense fallback={null}>
          <PointCloudModel url={plyUrl} />
        </Suspense>
        <OrbitControls
          enableDamping
          dampingFactor={0.05}
          minDistance={0.1}
          maxDistance={500}
        />
        <Grid
          args={[20, 20]}
          cellSize={0.5}
          cellThickness={0.5}
          cellColor="#222233"
          sectionSize={5}
          sectionThickness={1}
          sectionColor="#333355"
          fadeDistance={25}
          position={[0, -1, 0]}
        />
        <Environment preset="night" />
      </Canvas>

      {/* Overlay info */}
      <div className="absolute bottom-3 left-3 bg-black/60 backdrop-blur-sm rounded-lg px-3 py-2 text-xs text-text-muted">
        <div>Left drag: Rotate &middot; Right drag: Pan &middot; Scroll: Zoom</div>
      </div>
    </div>
  );
}
