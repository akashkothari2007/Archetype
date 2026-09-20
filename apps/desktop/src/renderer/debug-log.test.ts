import {afterEach,describe,expect,it,vi} from 'vitest';
import {beginNetwork,endNetwork,formatArgs,logEntries,recordConsole,resetDebugLog,shortUrl,subscribeLogs} from './debug-log';

afterEach(()=>{
  resetDebugLog();
  vi.unstubAllGlobals();
});

describe('debug log',()=>{
  it('shortens desktop API urls to the path',()=>{
    expect(shortUrl('http://127.0.0.1:8000/api/desktop/projects')).toBe('/projects');
  });

  it('formats console arguments and records them',()=>{
    expect(formatArgs(['hello',{a:1},new Error('nope')])).toContain('hello');
    recordConsole('warn',['slow tile']);
    expect(logEntries()[0]).toMatchObject({kind:'console',level:'warn',text:'slow tile'});
  });

  it('updates in-flight network rows when they finish',()=>{
    const id=beginNetwork('POST','http://127.0.0.1:8000/api/desktop/generate','{"name":"Willow"}');
    expect(logEntries()[0].pending).toBe(true);
    endNetwork(id,{status:200,ms:42,body:'{"ok":true}'});
    expect(logEntries()[0]).toMatchObject({pending:false,status:200,text:'/generate 200 42ms'});
    expect(logEntries()[0].detail).toContain('→ {"name":"Willow"}');
    expect(logEntries()[0].detail).toContain('← {"ok":true}');
  });

  it('notifies subscribers after a change',async()=>{
    const fn=vi.fn();
    subscribeLogs(fn);
    recordConsole('log',['hi']);
    await vi.waitFor(()=>expect(fn).toHaveBeenCalled());
  });
});
