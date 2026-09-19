import { useEffect, useRef } from 'react'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'

type Bounds = { cx: number; cy: number; width: number; height: number }

export function ExteriorSplat({ url, bounds, height }: { url: string; bounds: Bounds; height: number }) {
  const { gl, scene, invalidate } = useThree()
  const group = useRef<THREE.Group>(null)
  useEffect(() => {
    let cancelled = false
    let spark: THREE.Object3D | null = null
    let splat: THREE.Object3D | null = null
    import('@sparkjsdev/spark').then(({ SparkRenderer, SplatMesh }) => {
      if (cancelled) return
      spark = new SparkRenderer({ renderer: gl, onDirty: () => invalidate() })
      splat = new SplatMesh({
        url,
        onLoad: (mesh: THREE.Object3D) => {
          if (cancelled) return
          mesh.quaternion.set(1, 0, 0, 0)
          mesh.updateMatrixWorld(true)
          const box = new THREE.Box3().setFromObject(mesh)
          if (box.isEmpty()) return
          const size = box.getSize(new THREE.Vector3())
          const center = box.getCenter(new THREE.Vector3())
          const scale = Math.min(
            bounds.width / Math.max(size.x, 0.01),
            Math.max(height, 8) / Math.max(size.y, 0.01),
            bounds.height / Math.max(size.z, 0.01),
          ) * 1.04
          mesh.scale.setScalar(scale)
          mesh.position.set(
            bounds.cx - center.x * scale,
            Math.max(height, 8) * 0.45 - center.y * scale,
            bounds.cy - center.z * scale,
          )
          invalidate()
        },
      })
      spark.add(splat)
      scene.add(spark)
    }).catch(() => undefined)
    return () => {
      cancelled = true
      if (spark) scene.remove(spark)
    }
  }, [url, gl, scene, invalidate, bounds.cx, bounds.cy, bounds.width, bounds.height, height])
  return <group ref={group} userData={{ captureHide: true }} />
}
