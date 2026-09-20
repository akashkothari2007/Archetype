import {contextBridge,ipcRenderer} from 'electron';
contextBridge.exposeInMainWorld('archetype',{
  platform:process.platform,
  importFolder:()=>ipcRenderer.invoke('project:import-folder'),
  popupMenu:(name:string,x:number,y:number)=>ipcRenderer.invoke('menu:popup',name,x,y),
  onMenuCommand:(cb:(command:string)=>void)=>{
    const listener=(_event:unknown,command:string)=>cb(command);
    ipcRenderer.on('menu:command',listener);
    return ()=>ipcRenderer.removeListener('menu:command',listener);
  }
});
