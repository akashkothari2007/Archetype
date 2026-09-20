import {defineConfig} from 'electron-vite';
import react from '@vitejs/plugin-react';
import {resolve} from 'node:path';
export default defineConfig({main:{build:{rollupOptions:{input:resolve('src/main/index.ts')}}},preload:{build:{rollupOptions:{input:resolve('src/preload/index.ts')}}},renderer:{root:'.',publicDir:'public',envDir:resolve(__dirname,'../..'),plugins:[react()],optimizeDeps:{exclude:['maplibre-gl','@sparkjsdev/spark']},server:{host:'127.0.0.1',port:5173,strictPort:true},build:{rollupOptions:{input:resolve('index.html')}}}});
