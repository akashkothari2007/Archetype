import {contextBridge,ipcRenderer} from 'electron';
contextBridge.exposeInMainWorld('archetype',{importFolder:()=>ipcRenderer.invoke('project:import-folder')});
