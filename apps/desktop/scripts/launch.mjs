import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const bin = join(dirname(require.resolve('electron-vite/package.json')), 'bin', 'electron-vite.js')
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
const child = spawn(process.execPath, [bin, ...process.argv.slice(2)], { stdio: 'inherit', env })
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  process.exit(code ?? 1)
})
