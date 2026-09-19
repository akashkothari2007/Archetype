import {spawn,spawnSync} from 'node:child_process';
import {existsSync,copyFileSync} from 'node:fs';
const local=process.argv.includes('--local');
const children=[];
if(!existsSync('.env'))copyFileSync('.env.example','.env');
if(local){const python=process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python';if(!existsSync(python)){console.error('Create the Python environment first. See README.md.');process.exit(1)}children.push(spawn(python,['-m','uvicorn','plancheck.api.main:app','--host','127.0.0.1','--port','8000','--log-level','info'],{stdio:'inherit',env:{...process.env,PYTHONUNBUFFERED:'1'}}));}else{const result=spawnSync('docker',['compose','up','-d','--build'],{stdio:'inherit',shell:process.platform==='win32'});if(result.status!==0){console.error('Docker is unavailable. Use pnpm dev:local after installing Python dependencies.');process.exit(1)}}
let ready=false;for(let i=0;i<90;i++){try{const r=await fetch('http://127.0.0.1:8000/api/desktop/health');if(r.ok){ready=true;break}}catch{}await new Promise(r=>setTimeout(r,1000))}if(!ready){console.error('Backend did not become ready.');process.exit(1)}
const env={...process.env};delete env.ELECTRON_RUN_AS_NODE
const desktop=spawn('pnpm',['--filter','@archetype/desktop','dev'],{stdio:'inherit',shell:process.platform==='win32',env});children.push(desktop);
const stop=()=>{for(const c of children)c.kill();process.exit()};process.on('SIGINT',stop);process.on('SIGTERM',stop);desktop.on('exit',stop);
