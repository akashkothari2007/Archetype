import * as THREE from 'three'

export type GuideCapture = { image: string; projector: number[] }

function isoCamera(bounds: { cx: number; cy: number; width: number; height: number }, roof: number) {
  const span = Math.max(bounds.width, bounds.height, roof, 12)
  const elevation = Math.atan(1 / Math.sqrt(2))
  const azimuth = Math.PI / 4
  const distance = span * 2.2
  const camera = new THREE.OrthographicCamera(-span, span, span, -span, 0.2, distance * 8)
  camera.position.set(
    bounds.cx + Math.cos(azimuth) * Math.cos(elevation) * distance,
    Math.sin(elevation) * distance + roof * 0.35,
    bounds.cy + Math.sin(azimuth) * Math.cos(elevation) * distance,
  )
  camera.lookAt(bounds.cx, roof * 0.35, bounds.cy)
  camera.updateMatrixWorld()
  const box = new THREE.Box3(
    new THREE.Vector3(bounds.cx - bounds.width / 2, 0, bounds.cy - bounds.height / 2),
    new THREE.Vector3(bounds.cx + bounds.width / 2, Math.max(roof, 8), bounds.cy + bounds.height / 2),
  )
  const ndc = new THREE.Vector3()
  let minX = 1, minY = 1, maxX = -1, maxY = -1
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    ndc.set(x, y, z).project(camera)
    minX = Math.min(minX, ndc.x); maxX = Math.max(maxX, ndc.x)
    minY = Math.min(minY, ndc.y); maxY = Math.max(maxY, ndc.y)
  }
  const pad = 0.04
  const halfW = Math.max(0.08, (maxX - minX) / 2 + pad)
  const halfH = Math.max(0.08, (maxY - minY) / 2 + pad)
  const midX = (minX + maxX) / 2
  const midY = (minY + maxY) / 2
  const worldW = (camera.right - camera.left) * halfW
  const worldH = (camera.top - camera.bottom) * halfH
  const cx = (camera.left + camera.right) / 2 + midX * (camera.right - camera.left) / 2
  const cy = (camera.top + camera.bottom) / 2 + midY * (camera.top - camera.bottom) / 2
  camera.left = cx - worldW
  camera.right = cx + worldW
  camera.top = cy + worldH
  camera.bottom = cy - worldH
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld()
  return camera
}

function hideForCapture(root: THREE.Object3D) {
  const hidden: Array<{ object: THREE.Object3D; visible: boolean }> = []
  root.traverse(object => {
    if (object.userData.captureHide || object.type === 'TransformControls' || object.type === 'AxesHelper') {
      hidden.push({ object, visible: object.visible })
      object.visible = false
    }
  })
  return () => { for (const item of hidden) item.object.visible = item.visible }
}

function unlit(root: THREE.Object3D) {
  const swapped: Array<{ mesh: THREE.Mesh; material: THREE.Material | THREE.Material[] }> = []
  root.traverse(object => {
    if (!(object instanceof THREE.Mesh) || !object.visible) return
    swapped.push({ mesh: object, material: object.material })
    const source = Array.isArray(object.material) ? object.material[0] : object.material
    const color = source && 'color' in source ? (source as THREE.MeshStandardMaterial).color.clone() : new THREE.Color('#9b9b9b')
    object.material = new THREE.MeshBasicMaterial({ color, toneMapped: false })
  })
  return () => {
    for (const item of swapped) {
      const current = item.mesh.material
      item.mesh.material = item.material
      if (current && current !== item.material) {
        const list = Array.isArray(current) ? current : [current]
        list.forEach(material => material.dispose())
      }
    }
  }
}

export function captureGuide(
  gl: THREE.WebGLRenderer,
  scene: THREE.Scene,
  bounds: { cx: number; cy: number; width: number; height: number },
  roof: number,
): GuideCapture {
  const size = 1024
  const camera = isoCamera(bounds, roof)
  const target = new THREE.WebGLRenderTarget(size, size, { colorSpace: THREE.SRGBColorSpace })
  const restoreHide = hideForCapture(scene)
  const restoreMaterials = unlit(scene)
  const previous = {
    target: gl.getRenderTarget(),
    tone: gl.toneMapping,
    exposure: gl.toneMappingExposure,
    clear: gl.getClearColor(new THREE.Color()),
    alpha: gl.getClearAlpha(),
    background: scene.background,
    override: scene.overrideMaterial,
  }
  try {
    gl.toneMapping = THREE.NoToneMapping
    gl.toneMappingExposure = 1
    scene.background = new THREE.Color('#000000')
    gl.setRenderTarget(target)
    gl.setClearColor('#000000', 1)
    gl.clear()
    gl.render(scene, camera)
    const buffer = new Uint8Array(size * size * 4)
    gl.readRenderTargetPixels(target, 0, 0, size, size, buffer)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = size
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Could not read the 3D snapshot')
    const image = ctx.createImageData(size, size)
    for (let y = 0; y < size; y++) {
      const src = (size - 1 - y) * size * 4
      const dst = y * size * 4
      image.data.set(buffer.subarray(src, src + size * 4), dst)
    }
    ctx.putImageData(image, 0, 0)
    const projector = new THREE.Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse)
    return { image: canvas.toDataURL('image/png'), projector: projector.toArray() }
  } finally {
    gl.setRenderTarget(previous.target)
    gl.toneMapping = previous.tone
    gl.toneMappingExposure = previous.exposure
    gl.setClearColor(previous.clear, previous.alpha)
    scene.background = previous.background
    scene.overrideMaterial = previous.override
    restoreMaterials()
    restoreHide()
    target.dispose()
    camera.removeFromParent()
  }
}
