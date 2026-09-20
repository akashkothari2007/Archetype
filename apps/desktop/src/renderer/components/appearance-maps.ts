import * as THREE from 'three'

function luminance(r: number, g: number, b: number) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function scorePatch(data: Uint8ClampedArray, width: number, x: number, y: number, size: number, kind: 'wall' | 'roof') {
  let dark = 0, count = 0, lumaSum = 0, lumaSq = 0, red = 0, blue = 0
  const step = Math.max(1, Math.floor(size / 24))
  for (let py = y; py < y + size; py += step) {
    for (let px = x; px < x + size; px += step) {
      const i = (py * width + px) * 4
      const r = data[i], g = data[i + 1], b = data[i + 2]
      const luma = luminance(r, g, b)
      count += 1
      lumaSum += luma
      lumaSq += luma * luma
      red += r
      blue += b
      if (r + g + b < 42) dark += 1
    }
  }
  if (!count) return -1
  const mean = lumaSum / count
  const variance = Math.max(0, lumaSq / count - mean * mean)
  const darkFrac = dark / count
  if (darkFrac > 0.32 || mean < 38 || mean > 208) return -1
  const warm = (red - blue) / count
  return kind === 'wall' ? variance + warm * 0.45 - darkFrac * 90 : variance * 0.7 - Math.abs(warm) * 0.15 - darkFrac * 90
}

function cropBest(image: CanvasImageSource, width: number, height: number, kind: 'wall' | 'roof') {
  const src = document.createElement('canvas')
  src.width = width
  src.height = height
  const ctx = src.getContext('2d')
  if (!ctx) throw new Error('Could not read the appearance photograph')
  ctx.drawImage(image, 0, 0)
  const { data } = ctx.getImageData(0, 0, width, height)
  let minX = width, minY = height, maxX = 0, maxY = 0
  for (let y = 0; y < height; y += 2) {
    for (let x = 0; x < width; x += 2) {
      const i = (y * width + x) * 4
      if (data[i] + data[i + 1] + data[i + 2] > 40) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x)
        minY = Math.min(minY, y); maxY = Math.max(maxY, y)
      }
    }
  }
  if (maxX <= minX || maxY <= minY) {
    minX = 0; minY = 0; maxX = width - 1; maxY = height - 1
  }
  const bw = maxX - minX, bh = maxY - minY
  const size = Math.max(32, Math.min(256, Math.floor(Math.min(bw, bh) * (kind === 'roof' ? 0.28 : 0.36))))
  const yStart = kind === 'roof' ? minY : minY + Math.floor(bh * 0.34)
  const yEnd = kind === 'roof' ? minY + Math.max(size, Math.floor(bh * 0.42)) : maxY - size
  let best = { score: -1, x: minX, y: yStart }
  const step = Math.max(6, Math.floor(size / 4))
  for (let y = yStart; y <= Math.max(yStart, yEnd); y += step) {
    for (let x = minX; x <= maxX - size; x += step) {
      const score = scorePatch(data, width, x, y, size, kind)
      if (score > best.score) best = { score, x, y }
    }
  }
  const out = document.createElement('canvas')
  out.width = out.height = 256
  const octx = out.getContext('2d')
  if (!octx) throw new Error('Could not crop cladding')
  octx.imageSmoothingEnabled = true
  octx.drawImage(src, best.x, best.y, size, size, 0, 0, 256, 256)
  return out
}

function textureFromCanvas(canvas: HTMLCanvasElement) {
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.minFilter = THREE.LinearMipmapLinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.generateMipmaps = true
  texture.needsUpdate = true
  return texture
}

export async function claddingFromPng(blob: Blob) {
  const bitmap = await createImageBitmap(blob)
  try {
    return {
      wall: textureFromCanvas(cropBest(bitmap, bitmap.width, bitmap.height, 'wall')),
      roof: textureFromCanvas(cropBest(bitmap, bitmap.width, bitmap.height, 'roof')),
    }
  } finally {
    bitmap.close()
  }
}

export async function loadRepeatTexture(url: string) {
  const response = await fetch(url)
  if (!response.ok) return null
  const objectUrl = URL.createObjectURL(await response.blob())
  try {
    return await new Promise<THREE.Texture>((resolve, reject) => {
      new THREE.TextureLoader().load(objectUrl, texture => {
        texture.colorSpace = THREE.SRGBColorSpace
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping
        texture.needsUpdate = true
        resolve(texture)
      }, undefined, () => reject(new Error('Could not load cladding')))
    })
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}
