// Reproducible CC0 material import. Run from the repository root:
//   node scripts/fetch-material-assets.mjs
import { createWriteStream } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'

const root = 'apps/desktop/public/assets/materials'
const manifestPath = join(root, 'manifest.json')
const ids = [
  'beige_wall_001',
  'slate_floor',
  'american_walnut_veneer',
  'stone_tiles',
  'concrete_floor',
  'brick_wall_001',
  'herringbone_parquet',
  'marble_01',
  'terracotta_floor_tiles',
  'cobblestone_04',
  'metal_plate',
  'long_white_tiles',
  'dark_wood',
  'painted_brick',
  'granite_tile',
]

async function download(url, path) {
  const response = await fetch(url, { headers: { 'User-Agent': 'Archetype/1.0' } })
  if (!response.ok) throw new Error(`${response.status}: ${url}`)
  await mkdir(dirname(path), { recursive: true })
  await pipeline(Readable.fromWeb(response.body), createWriteStream(path))
}

async function filesFor(id) {
  const response = await fetch(`https://api.polyhaven.com/files/${id}`, { headers: { 'User-Agent': 'Archetype/1.0' } })
  if (!response.ok) throw new Error(`${response.status}: files/${id}`)
  return response.json()
}

async function infoFor(id) {
  const response = await fetch(`https://api.polyhaven.com/info/${id}`, { headers: { 'User-Agent': 'Archetype/1.0' } })
  if (!response.ok) throw new Error(`${response.status}: info/${id}`)
  return response.json()
}

function thumbUrl(id) {
  return `https://cdn.polyhaven.com/asset_img/thumbs/${id}.png?width=256&height=256`
}

const manifest = []
for (const id of ids) {
  console.log(`Fetching ${id}…`)
  const [files, info] = await Promise.all([filesFor(id), infoFor(id)])
  const dest = join(root, id)
  const fileRecords = []
  for (const key of ['Diffuse', 'nor_gl', 'Rough']) {
    const file = files[key]?.['1k']?.jpg
    if (!file?.url) throw new Error(`${id} missing 1k ${key}`)
    await download(file.url, join(dest, `${key}.jpg`))
    fileRecords.push({ path: `${key}.jpg`, source: file.url, md5: file.md5 || '', bytes: file.size || 0 })
  }
  try {
    await download(thumbUrl(id), join(dest, 'preview.png'))
    fileRecords.push({ path: 'preview.png', source: thumbUrl(id), md5: '', bytes: 0 })
  } catch (error) {
    console.warn(`  preview skipped: ${error.message}`)
  }
  manifest.push({
    id,
    name: info.name || id,
    source: `https://polyhaven.com/a/${id}`,
    license: 'CC0-1.0',
    license_url: 'https://polyhaven.com/license',
    authors: info.authors || {},
    resolution: '1k',
    files: fileRecords,
  })
  console.log(`  saved ${id}`)
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
console.log(`Wrote ${manifest.length} materials to ${manifestPath}`)
