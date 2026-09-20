import {app,BrowserWindow,dialog,ipcMain,Menu,nativeTheme} from 'electron';
import type {MenuItemConstructorOptions} from 'electron';
import {join,basename} from 'node:path';
import {readdir,readFile,writeFile} from 'node:fs/promises';
import {openAsBlob} from 'node:fs';

const backend='http://127.0.0.1:8000/api/desktop';
const TITLEBAR_HEIGHT=48;
const CHROME='#f3f4ee';
const CHROME_SYMBOL='#3a4136';

nativeTheme.themeSource='light';
app.setName('Archetype');

async function scan(dir:string):Promise<string[]>{
  const out:string[]=[];
  for(const item of await readdir(dir,{withFileTypes:true})){
    if(item.name.startsWith('.')||['node_modules','revisions'].includes(item.name))continue;
    const path=join(dir,item.name);
    if(item.isDirectory())out.push(...await scan(path));
    else if(/\.(pdf|dxf|ifc|md)$/i.test(item.name))out.push(path);
  }
  return out;
}

function send(window:BrowserWindow,command:string){
  return ()=>window.webContents.send('menu:command',command);
}

function buildMenu(window:BrowserWindow){
  const template:MenuItemConstructorOptions[]=[
    {
      label:'File',
      submenu:[
        {label:'New Project',accelerator:'CmdOrCtrl+N',click:send(window,'new-project')},
        {label:'Import Project…',accelerator:'CmdOrCtrl+O',click:send(window,'import')},
        {type:'separator'},
        {label:'Export Chat…',accelerator:'CmdOrCtrl+Shift+E',click:send(window,'export-chat')},
        {label:'Export Schematic…',accelerator:'CmdOrCtrl+Shift+P',click:send(window,'export-schematic')},
        {type:'separator'},
        {label:'Close Project',click:send(window,'close-project')},
        {type:'separator'},
        process.platform==='darwin'?{role:'close'}:{role:'quit'}
      ]
    },
    {
      label:'Edit',
      submenu:[
        {label:'Undo',accelerator:'CmdOrCtrl+Z',registerAccelerator:false,click:send(window,'undo')},
        {label:'Redo',accelerator:'CmdOrCtrl+Shift+Z',registerAccelerator:false,click:send(window,'redo')},
        {type:'separator'},
        {role:'cut'},
        {role:'copy'},
        {role:'paste'},
        {role:'selectAll'}
      ]
    },
    {
      label:'View',
      submenu:[
        {label:'Reset Layout',click:send(window,'reset-layout')},
        {type:'separator'},
        {role:'reload'},
        {role:'toggleDevTools'},
        {type:'separator'},
        {role:'resetZoom'},
        {role:'zoomIn'},
        {role:'zoomOut'},
        {type:'separator'},
        {role:'togglefullscreen'}
      ]
    },
    {
      label:'Help',
      submenu:[
        {label:'About Archetype',click:()=>{
          dialog.showMessageBox(window,{
            type:'info',
            title:'About Archetype',
            message:'Archetype',
            detail:'A thoughtful space to design, explore, and refine.',
            buttons:['OK']
          });
        }}
      ]
    }
  ];
  if(process.platform==='darwin'){
    template.unshift({
      role:'appMenu',
      submenu:[
        {role:'about'},
        {type:'separator'},
        {role:'services'},
        {type:'separator'},
        {role:'hide'},
        {role:'hideOthers'},
        {role:'unhide'},
        {type:'separator'},
        {role:'quit'}
      ]
    });
  }
  const menu=Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
  return menu;
}

app.whenReady().then(()=>{
  const mac=process.platform==='darwin';
  const win32=process.platform==='win32';
  const window=new BrowserWindow({
    width:1480,
    height:950,
    minWidth:1000,
    minHeight:680,
    title:'Archetype',
    show:false,
    backgroundColor:CHROME,
    autoHideMenuBar:true,
    titleBarStyle:'hidden',
    ...(mac?{
      trafficLightPosition:{x:14,y:10}
    }:{}),
    ...(win32?{
      titleBarOverlay:{
        color:CHROME,
        symbolColor:CHROME_SYMBOL,
        height:TITLEBAR_HEIGHT
      }
    }:{}),
    ...(!mac&&!win32?{
      titleBarOverlay:{
        color:CHROME,
        symbolColor:CHROME_SYMBOL,
        height:TITLEBAR_HEIGHT
      }
    }:{}),
    webPreferences:{
      preload:join(__dirname,'../preload/index.js'),
      contextIsolation:true,
      nodeIntegration:false,
      sandbox:true
    }
  });

  const menu=buildMenu(window);
  if(!mac) window.setMenuBarVisibility(false);

  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.once('ready-to-show',()=>window.show());

  ipcMain.removeHandler('menu:popup');
  ipcMain.handle('menu:popup',(event,name:string,x:number,y:number)=>{
    const item=menu.items.find(entry=>entry.label===name);
    const host=BrowserWindow.fromWebContents(event.sender)??window;
    item?.submenu?.popup({window:host,x:Math.round(x),y:Math.round(y)});
  });

  ipcMain.removeHandler('project:import-folder');
  ipcMain.handle('project:import-folder',async()=>{
    const choice=await dialog.showOpenDialog(window,{properties:['openDirectory'],title:'Import an Archetype project or source folder'});
    if(choice.canceled)return null;
    const dir=choice.filePaths[0];
    try{
      const m=JSON.parse(await readFile(join(dir,'project.json'),'utf8'));
      const s=JSON.parse(await readFile(join(dir,'revisions',String(m.current_revision),'model.json'),'utf8'));
      const r=await fetch(backend+'/import-native',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:m.name,brief:m.brief,...s})});
      if(!r.ok)throw Error(await r.text());
      return r.json();
    }catch(e){
      if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;
    }
    const files=await scan(dir);
    if(!files.length)throw Error('This folder has no supported PDF, DXF, or IFC sources.');
    const form=new FormData();
    for(const path of files)form.append('files',await openAsBlob(path),path.slice(dir.length+1));
    form.append('name',basename(dir));
    const response=await fetch(backend+'/import',{method:'POST',body:form});
    if(!response.ok)throw Error(await response.text());
    return response.json();
  });

  ipcMain.removeHandler('file:save-text');
  ipcMain.handle('file:save-text',async(_event,name:string,content:string)=>{
    const svg=name.toLowerCase().endsWith('.svg');
    const choice=await dialog.showSaveDialog(window,{
      title:svg?'Export schematic':'Export chat',
      defaultPath:name,
      filters:svg
        ?[{name:'SVG',extensions:['svg']},{name:'All Files',extensions:['*']}]
        :[{name:'Markdown',extensions:['md']},{name:'All Files',extensions:['*']}]
    });
    if(choice.canceled||!choice.filePath)return null;
    await writeFile(choice.filePath,content,'utf8');
    return choice.filePath;
  });

  if(process.env.ELECTRON_RENDERER_URL)window.loadURL(process.env.ELECTRON_RENDERER_URL);
  else window.loadFile(join(__dirname,'../renderer/index.html'));
});

app.on('window-all-closed',()=>{if(process.platform!=='darwin')app.quit()});
