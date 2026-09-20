// Reproducible CC0 furniture import. Run from the repository root:
//   node scripts/fetch-furniture-assets.mjs
import { createWriteStream } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'

const root = 'apps/desktop/public/assets'
const catalogPath = 'apps/desktop/src/renderer/furniture-catalog.json'
const manifestPath = join(root, 'catalog-manifest.json')

async function download(url, path) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${response.status}: ${url}`)
  await mkdir(dirname(path), { recursive: true })
  await pipeline(Readable.fromWeb(response.body), createWriteStream(path))
}

async function filesFor(id) {
  const response = await fetch(`https://api.polyhaven.com/files/${id}`)
  if (!response.ok) throw new Error(`${response.status}: files/${id}`)
  return response.json()
}

async function infoFor(id) {
  const response = await fetch(`https://api.polyhaven.com/info/${id}`)
  if (!response.ok) throw new Error(`${response.status}: info/${id}`)
  return response.json()
}

function gltfEntry(files) {
  const gltf = files?.gltf?.['1k']?.gltf
  if (!gltf?.url) throw new Error('missing 1k gltf')
  return gltf
}

function thumbUrl(id) {
  return `https://cdn.polyhaven.com/asset_img/thumbs/${id}.png?width=256&height=256`
}

const catalog = JSON.parse(await readFile(catalogPath, 'utf8'))
const manifest = []

for (const item of catalog) {
  const id = item.id
  console.log(`Fetching ${id}…`)
  const [files, info] = await Promise.all([filesFor(id), infoFor(id)])
  const gltf = gltfEntry(files)
  const dest = join(root, id)
  await download(gltf.url, join(dest, `${id}.gltf`))
  const fileRecords = [{ path: `${id}.gltf`, source: gltf.url, md5: gltf.md5 || '', bytes: gltf.size || 0 }]
  for (const [rel, file] of Object.entries(gltf.include || {})) {
    await download(file.url, join(dest, rel))
    fileRecords.push({ path: rel, source: file.url, md5: file.md5 || '', bytes: file.size || 0 })
  }
  try {
    await download(thumbUrl(id), join(dest, 'preview.png'))
  } catch (error) {
    console.warn(`  preview skipped: ${error.message}`)
  }
  manifest.push({
    id,
    name: info.name || item.label,
    source: `https://polyhaven.com/a/${id}`,
    license: 'CC0-1.0',
    license_url: 'https://polyhaven.com/license',
    authors: info.authors || {},
    resolution: '1k',
    path: `assets/${id}/${id}.gltf`,
    preview: `assets/${id}/preview.png`,
    files: fileRecords,
  })
  console.log(`  saved ${id}`)
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`)
console.log(`Wrote ${manifest.length} furniture assets to ${manifestPath}`)
