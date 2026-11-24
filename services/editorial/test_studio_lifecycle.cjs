'use strict';
// Execute the actual component's hook logic without a browser or network.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {stripTypeScriptTypes}=require('node:module');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'../..');
class Events {
 constructor(){this.listeners=new Map();}
 addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(fn);}
 removeEventListener(type,fn){this.listeners.get(type)?.delete(fn);}
 dispatchEvent(event){for(const fn of [...this.listeners.get(event.type)||[]])fn(event);}
}
const sameDeps=(left,right)=>left&&right&&left.length===right.length&&left.every((value,index)=>Object.is(value,right[index]));
function createHarness(helpers,initial,initialConnection=false){
 const source=fs.readFileSync(path.join(root,'apps/frontend/src/components/studio/studio.tsx'),'utf8');
 const logic=source.slice(0,source.lastIndexOf('\n  return (\n')).replace(/^import .*;\n/gm,'').replace('export function Studio','function Studio')+'\n return {route,frameSrc,ready,slow,retry,connection,navigate,syncRoute,host,frame};\n}\nglobalThis.Studio = Studio;';
 let current=new URL(initial);const win=new Events();const messages=[];const pushes=[];const nativePushes=[];const timers=new Map();let timerId=0;
 win.location={get href(){return current.href;},get origin(){return current.origin;},get pathname(){return current.pathname;},get search(){return current.search;},get hash(){return current.hash;}};
 win.history={pushState(data,title,value){pushes.push(value);current=new URL(value,current);},replaceState(data,title,value){current=new URL(value,current);}};
 win.visualViewport=Object.assign(new Events(),{height:800});win.innerHeight=800;
 win.setTimeout=(fn,ms)=>{const id=++timerId;timers.set(id,fn);return id;};win.clearTimeout=id=>timers.delete(id);
 const doc={body:{classList:{contains:()=>false}},documentElement:{style:{setProperty(){},removeProperty(){}}}};
 const frameWindow={postMessage:(data,origin)=>messages.push({data,origin})};
 const router={push:value=>nativePushes.push(value)};let hooks=[],cursor=0,effects=[],dirty=false,result;
 let queryKey=null,queryValue=null;
 const context={window:win,document:doc,console,URL,Record:undefined,...helpers,
  getComputedStyle:()=>({fontFamily:'Postiz',getPropertyValue:()=>''}),MutationObserver:class{observe(){}disconnect(){}},
  useRouter:()=>router,usePathname:()=>current.pathname,
  useSearchParams(){if(queryKey!==current.search){queryKey=current.search;queryValue=new URLSearchParams(queryKey);}return queryValue;},
  useRef(initial){const index=cursor++;return hooks[index]||(hooks[index]={current:initial});},
  useState(initial){const index=cursor++;if(!hooks[index]){const slot={value:typeof initial==='function'?initial():initial};slot.set=value=>{const next=typeof value==='function'?value(slot.value):value;if(!Object.is(next,slot.value)){slot.value=next;dirty=true;}};hooks[index]=slot;}return [hooks[index].value,hooks[index].set];},
  useCallback(fn,deps){const index=cursor++;if(!hooks[index]||!sameDeps(hooks[index].deps,deps))hooks[index]={fn,deps};return hooks[index].fn;},
  useEffect(fn,deps){const index=cursor++;if(!hooks[index]||!sameDeps(hooks[index].deps,deps)){const previous=hooks[index];hooks[index]={deps};effects.push(()=>{previous?.cleanup?.();hooks[index].cleanup=fn();});}},
 };
 vm.createContext(context);vm.runInContext(stripTypeScriptTypes(logic),context);
 function flush(){let rounds=0;do{if(++rounds>30)throw Error('Hook update loop');dirty=false;cursor=0;result=context.Studio({connection:initialConnection});result.host.current={};result.frame.current={contentWindow:frameWindow};const pending=effects;effects=[];for(const effect of pending)effect();}while(dirty||effects.length);return result;}
 function message(data,origin=current.origin,source=frameWindow){win.dispatchEvent({type:'message',origin,source,data:{namespace:'postiz-studio',...data}});flush();}
 flush();
 return {get state(){return result;},win,messages,pushes,nativePushes,frameWindow,timers,flush,message,
  navigate(value,fromFrame=false){result.navigate(value,fromFrame);flush();},
  go(value){current=new URL(value,current);win.dispatchEvent({type:'popstate'});flush();},
  url:()=>current.href,
  title:()=>doc.title,
  timeout(){for(const fn of [...timers.values()])fn();flush();},
 };
}

(async()=>{
 const helpers=await import(pathToFileURL(path.join(root,'apps/frontend/src/components/studio/studio-navigation.ts')));
 const origin='https://postiz.example.com';
 const tests=[];const test=(name,fn)=>tests.push({name,fn});
 test('initial shell retains deep link and accepts its frame readiness',()=>{
  const h=createHarness(helpers,origin+'/studio?conversation=c1&item=i1#contenus');
  assert.equal(h.state.route,'/studio?conversation=c1&item=i1#contenus');
  assert.equal(h.state.connection,false);
  assert.equal(h.state.ready,false);
  h.message({type:'ready',path:h.state.route});assert.equal(h.state.ready,true);
  assert.equal(h.state.frameSrc,'/editorial/?conversation=c1&item=i1&embedded=1#contenus');
  assert.equal(h.pushes.length,0);
 });
 test('content to connector to content has one history writer and one hash',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');const originalSrc=h.state.frameSrc;
  h.message({type:'ready',path:'/studio#contenus'});
  h.message({type:'navigate',path:'/studio/connect'});
  assert.equal(h.url(),origin+'/studio/connect');assert.equal(h.state.connection,true);assert.equal(h.state.ready,false);
  h.message({type:'ready',path:'/studio/connect'});assert.equal(h.state.ready,true);
  h.navigate('/studio#contenus');
  assert.equal(h.url(),origin+'/studio#contenus');assert.equal(h.state.connection,false);assert.equal(h.state.ready,false);
  h.message({type:'ready',path:'/studio#contenus'});assert.equal(h.state.ready,true);
  assert.deepEqual(h.pushes,['/studio/connect','/studio#contenus']);
  assert.deepEqual(h.nativePushes,[]);assert.equal(h.state.frameSrc,originalSrc);
  assert.equal(h.title(),'Postiz · Studio IA');
 });
 test('connector entrypoint also derives active screen from new route',()=>{
  const h=createHarness(helpers,origin+'/studio/connect',true);const originalSrc=h.state.frameSrc;
  h.message({type:'ready',path:'/studio/connect'});
  h.navigate('/studio#semaine');h.message({type:'ready',path:'/studio#semaine'});
  assert.equal(h.state.connection,false);assert.equal(h.state.route,'/studio#semaine');
  assert.equal(h.state.frameSrc,originalSrc);assert.deepEqual(h.nativePushes,[]);
  h.navigate('/studio/connect');h.message({type:'ready',path:'/studio/connect'});
  assert.equal(h.state.connection,true);assert.equal(h.title(),'Postiz · Connexion Grok Bot');
 });
 test('back and forward synchronise routes without adding history entries',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');h.message({type:'ready',path:'/studio#contenus'});
  h.navigate('/studio/connect');h.message({type:'ready',path:'/studio/connect'});
  h.navigate('/studio#semaine');h.message({type:'ready',path:'/studio#semaine'});
  const count=h.pushes.length;
  h.go('/studio/connect');assert.equal(h.state.connection,true);assert.equal(h.state.ready,false);
  h.message({type:'ready',path:'/studio/connect'});
  h.go('/studio#contenus');assert.equal(h.state.connection,false);h.message({type:'ready',path:'/studio#contenus'});
  h.go('/studio/connect');h.message({type:'ready',path:'/studio/connect'});
  h.go('/studio#semaine');h.message({type:'ready',path:'/studio#semaine'});
  assert.equal(h.pushes.length,count);assert.equal(h.state.route,'/studio#semaine');assert.deepEqual(h.nativePushes,[]);
 });
 test('old child readiness and route cannot replace a pending connector',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');h.message({type:'ready',path:'/studio#contenus'});
  h.navigate('/studio/connect');
  h.message({type:'ready',path:'/studio#contenus'});assert.equal(h.state.ready,false);
  h.message({type:'route',path:'/studio#discussion'});assert.equal(h.url(),origin+'/studio/connect');
  assert.deepEqual(h.pushes,['/studio/connect']);
  h.message({type:'ready',path:'/studio/connect'});assert.equal(h.state.ready,true);
 });
 test('query route reload keeps exact review and ignores stale document replies',()=>{
  const h=createHarness(helpers,origin+'/studio?conversation=c1#discussion');h.message({type:'ready',path:'/studio?conversation=c1#discussion'});
  h.navigate('/studio?conversation=c2&item=i2#discussion');assert.equal(h.state.ready,false);
  h.message({type:'ready',path:'/studio?conversation=c1#discussion'});assert.equal(h.state.ready,false);
  h.message({type:'route',path:'/studio?conversation=c1#discussion'});
  assert.equal(h.url(),origin+'/studio?conversation=c2&item=i2#discussion');
  h.message({type:'ready',path:'/studio?item=i2&conversation=c2#discussion'});assert.equal(h.state.ready,true);
  assert.equal(h.pushes.length,1);
 });
 test('child-selected discussion is already loaded and does not reset readiness',()=>{
  const h=createHarness(helpers,origin+'/studio#discussion');h.message({type:'ready',path:'/studio#discussion'});
  h.message({type:'route',path:'/studio?conversation=c2#discussion'});
  assert.equal(h.state.ready,true);assert.equal(h.url(),origin+'/studio?conversation=c2#discussion');
  assert.equal(h.pushes.length,1);assert.deepEqual(h.nativePushes,[]);
 });
 test('same route echoes do not add history or trigger loading',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');h.message({type:'ready',path:'/studio#contenus'});
  h.navigate('/studio#contenus');h.message({type:'route',path:'/studio#contenus'});
  assert.equal(h.state.ready,true);assert.equal(h.pushes.length,0);
 });
 test('external native destinations alone use the Next router',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');
  h.message({type:'navigate',path:'/launches'});h.message({type:'navigate',path:'/auth/login'});
  h.message({type:'navigate',path:'https://evil.example/studio'});
  assert.deepEqual(h.nativePushes,['/launches','/auth/login']);assert.equal(h.pushes.length,0);
 });
 test('wrong origin and wrong source cannot control the native shell',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');
  h.message({type:'ready',path:'/studio#contenus'},'https://evil.example');
  h.message({type:'navigate',path:'/studio/connect'},origin,{});
  h.message({type:'navigate',path:'/launches'},'https://evil.example');
  assert.equal(h.state.ready,false);assert.equal(h.pushes.length,0);assert.deepEqual(h.nativePushes,[]);
 });
 test('failure to load a later connector offers retry state again',()=>{
  const h=createHarness(helpers,origin+'/studio#contenus');h.message({type:'ready',path:'/studio#contenus'});
  h.navigate('/studio/connect');h.timeout();assert.equal(h.state.ready,false);assert.equal(h.state.slow,true);
 });
 let failed=0;for(const {name,fn} of tests){try{fn();console.log('PASS '+name);}catch(error){failed++;console.error('FAIL '+name+'\n'+error.stack);}}
 console.log(`${tests.length-failed}/${tests.length} native lifecycle checks passed`);process.exitCode=failed?1:0;
})().catch(error=>{console.error(error);process.exitCode=1;});
