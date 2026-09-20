import { useEffect, useRef } from 'react'
import { useThree } from '@react-three/fiber'
import * as THREE from 'three'

import { SPLAT_UPRIGHT, fitObjectSplat, robustSplatBounds, splatExtents, splatFileHint, splatPlacement, type SplatBounds } from './scene-splat-fit'
import type { SplatFileType } from '@sparkjsdev/spark'

type Bounds = { cx: number; cy: number; width: number; height: number }
type SparkMesh = THREE.Object3D & { getBoundingBox?: (centers?: boolean) => THREE.Box3; dispose?: () => void }
type SparkRendererMesh = THREE.Mesh & { dispose?: () => void }

function splatAabb(mesh: SparkMesh, measured?: SplatBounds | null) {
  if (measured) return measured
  try {
    const box = mesh.getBoundingBox?.(true)
    if (box && Number.isFinite(box.min.x) && Number.isFinite(box.max.x) && box.max.x - box.min.x > 1e-4) {
      return { min: box.min, max: box.max }
    }
  } catch {
    /* SplatMesh is an Object3D with no Three geometry; Box3.setFromObject is empty. */
  }
  return { min: { x: -0.5, y: -0.5, z: -0.5 }, max: { x: 0.5, y: 0.5, z: 0.5 } }
}

export function fitSplatMesh(mesh: SparkMesh, bounds: Bounds, height: number, measured?: SplatBounds | null) {
  // TripoSplat arrives image-down. Use a proper rotation rather than a negative
  // scale: Spark's Gaussian covariance/culling assumes a positive determinant.
  mesh.quaternion.set(SPLAT_UPRIGHT.x, SPLAT_UPRIGHT.y, SPLAT_UPRIGHT.z, SPLAT_UPRIGHT.w)
  const aabb = splatAabb(mesh, measured)
  const extents = splatExtents(aabb.min, aabb.max, SPLAT_UPRIGHT)
  const place = splatPlacement(extents.size, extents.center, extents.minY, bounds, height)
  mesh.scale.set(place.scale.x, place.scale.y, place.scale.z)
  mesh.position.set(place.x, place.y, place.z)
  mesh.updateMatrixWorld(true)
}

export function fitObjectSplatMesh(mesh: SparkMesh, box: { width: number; height: number; depth: number }, measured?: SplatBounds | null) {
  mesh.quaternion.set(SPLAT_UPRIGHT.x, SPLAT_UPRIGHT.y, SPLAT_UPRIGHT.z, SPLAT_UPRIGHT.w)
  const aabb = splatAabb(mesh, measured)
  const extents = splatExtents(aabb.min, aabb.max, SPLAT_UPRIGHT)
  const place = fitObjectSplat(extents.size, extents.center, extents.minY, box)
  mesh.scale.setScalar(place.scale)
  mesh.position.set(place.x, place.y, place.z)
  mesh.updateMatrixWorld(true)
}

export function ExteriorSplat({ url, bounds, height, onReady }: { url: string; bounds: Bounds; height: number; onReady?: () => void }) {
  const gl = useThree(state => state.gl)
  const invalidate = useThree(state => state.invalidate)
  const group = useRef<THREE.Group>(null)
  const meshRef = useRef<SparkMesh | null>(null)
  const measuredRef = useRef<SplatBounds | null>(null)
  const boundsRef = useRef(bounds)
  const heightRef = useRef(height)
  const onReadyRef = useRef(onReady)
  boundsRef.current = bounds
  heightRef.current = height
  onReadyRef.current = onReady

  useEffect(() => {
    const mesh = meshRef.current
    if (!mesh) return
    fitSplatMesh(mesh, bounds, height, measuredRef.current)
    invalidate()
  }, [bounds.cx, bounds.cy, bounds.width, bounds.height, height, invalidate])

  useEffect(() => {
    const host = group.current
    if (!host) return
    let cancelled = false
    let spark: SparkRendererMesh | null = null
    let splat: SparkMesh | null = null

    ;(async () => {
      const [{ SparkRenderer, SplatMesh }, response] = await Promise.all([
        import('@sparkjsdev/spark'),
        fetch(url),
      ])
      if (cancelled) return
      if (!response.ok) throw new Error(`Could not load the Gaussian splat (${response.status}).`)
      const fileBytes = await response.arrayBuffer()
      if (cancelled) return
      spark = new SparkRenderer({ renderer: gl, onDirty: () => invalidate() })
      const material = spark.material
      if (!Array.isArray(material)) material.toneMapped = false
      const hint = splatFileHint(url)
      measuredRef.current = robustSplatBounds(fileBytes, hint.fileType)
      splat = new SplatMesh({
        fileBytes,
        fileName: hint.fileName,
        fileType: hint.fileType as SplatFileType,
        onLoad: (mesh: SparkMesh) => {
          if (cancelled) return
          meshRef.current = mesh
          fitSplatMesh(mesh, boundsRef.current, heightRef.current, measuredRef.current)
          invalidate()
          onReadyRef.current?.()
        },
      })
      spark.add(splat)
      host.add(spark)
      invalidate()
    })().catch(() => undefined)

    return () => {
      cancelled = true
      meshRef.current = null
      measuredRef.current = null
      splat?.removeFromParent()
      splat?.dispose?.()
      spark?.removeFromParent()
      spark?.dispose?.()
    }
  }, [url, gl, invalidate])

  return <group ref={group} userData={{ captureHide: true }} />
}

export function ObjectSplat({ url, width, height, depth, onReady }: { url: string; width: number; height: number; depth: number; onReady?: () => void }) {
  const gl = useThree(state => state.gl)
  const invalidate = useThree(state => state.invalidate)
  const group = useRef<THREE.Group>(null)
  const meshRef = useRef<SparkMesh | null>(null)
  const measuredRef = useRef<SplatBounds | null>(null)
  const boxRef = useRef({ width, height, depth })
  const onReadyRef = useRef(onReady)
  boxRef.current = { width, height, depth }
  onReadyRef.current = onReady

  useEffect(() => {
    const mesh = meshRef.current
    if (!mesh) return
    fitObjectSplatMesh(mesh, { width, height, depth }, measuredRef.current)
    invalidate()
  }, [width, height, depth, invalidate])

  useEffect(() => {
    const host = group.current
    if (!host) return
    let cancelled = false
    let spark: SparkRendererMesh | null = null
    let splat: SparkMesh | null = null

    ;(async () => {
      const [{ SparkRenderer, SplatMesh }, response] = await Promise.all([
        import('@sparkjsdev/spark'),
        fetch(url),
      ])
      if (cancelled) return
      if (!response.ok) throw new Error(`Could not load the furniture splat (${response.status}).`)
      const fileBytes = await response.arrayBuffer()
      if (cancelled) return
      spark = new SparkRenderer({ renderer: gl, onDirty: () => invalidate() })
      const material = spark.material
      if (!Array.isArray(material)) material.toneMapped = false
      const hint = splatFileHint(url)
      measuredRef.current = robustSplatBounds(fileBytes, hint.fileType)
      splat = new SplatMesh({
        fileBytes,
        fileName: hint.fileName,
        fileType: hint.fileType as SplatFileType,
        onLoad: (mesh: SparkMesh) => {
          if (cancelled) return
          meshRef.current = mesh
          fitObjectSplatMesh(mesh, boxRef.current, measuredRef.current)
          invalidate()
          onReadyRef.current?.()
        },
      })
      spark.add(splat)
      host.add(spark)
      invalidate()
    })().catch(() => undefined)

    return () => {
      cancelled = true
      meshRef.current = null
      measuredRef.current = null
      splat?.removeFromParent()
      splat?.dispose?.()
      spark?.removeFromParent()
      spark?.dispose?.()
    }
  }, [url, gl, invalidate])

  return <group ref={group} />
}
