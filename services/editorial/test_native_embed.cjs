'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
// Run with Node.js supporting native TypeScript stripping (22.18+).
// These tests execute the real bridge in a small DOM harness; no network calls.
const root = path.resolve(__dirname, '../..');
const tests=[];
const test=(name,run)=>tests.push({name,run});
class Events {
  constructor(){this.listeners={};}
  addEventListener(type, fn){(this.listeners[type] ||= []).push(fn);}
  dispatchEvent(event){for(const fn of this.listeners[event.type]||[]) fn(event);return true;}
}
function harness(initial, standalone=false){
  const changed=[]; const posts=[]; const timers=[]; let current=new URL(initial);
  const location={get href(){return current.href;},get origin(){return current.origin;},get pathname(){return current.pathname;},get search(){return current.search;},get hash(){return current.hash;},set hash(value){changed.push({kind:'hash',value});current.hash=value;},replace(value){changed.push({kind:'replace',value});current=new URL(value,current);},assign(value){changed.push({kind:'assign',value});current=new URL(value,current);}};
  const win=new Events();win.location=location;win.parent=standalone?win:{postMessage:(message,origin)=>posts.push({message,origin})};
  const props={};const classes=new Set();const document=new Events();document.documentElement={classList:{add:value=>classes.add(value)},dataset:{},style:{setProperty:(key,value)=>props[key]=value}};
  const elements={};document.getElementById=id=>elements[id]||null;
  const history={replaceState(data,title,value){changed.push({kind:'replaceState',value});current=new URL(value,current);},pushState(data,title,value){changed.push({kind:'pushState',value});current=new URL(value,current);}};
  win.history=history;win.document=document;
  const context={window:win,document,location,history,URL,Set,Object,console,setTimeout:fn=>timers.push(fn),HashChangeEvent:class{constructor(type,details){this.type=type;Object.assign(this,details);}},Event:class{constructor(type){this.type=type;}}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'services/editorial/static/embed.js'),'utf8'),context);
  function createLink(href, target='') {
    let value=href;
    return {
      get href(){return new URL(value,location.href).href;},
      set href(next){value=next;},
      target,
      getAttribute:key=>key==='href'?value:null,
      setAttribute(key,next){if(key==='href')value=next;},
      hasAttribute:()=>false,
    };
  }
  return {win,location,document,changed,posts,props,elements,classes,createLink,
    flushTimers(){while(timers.length)timers.shift()();},
    message(data,{origin=location.origin,source=win.parent}={}){win.dispatchEvent({type:'message',data:{namespace:'postiz-studio',...data},origin,source});},
    click(href,options={}){let prevented=false;const {target,...eventOptions}=options;const link=typeof href==='string'?createLink(href,target||''):href;document.dispatchEvent({type:'click',target:{closest:()=>link},button:0,defaultPrevented:false,preventDefault(){prevented=true;},...eventOptions});return {prevented,link};}
  };
}
(async()=>{
const {studioPath,embeddedPath,nativePath}=await import(pathToFileURL(path.join(root,'apps/frontend/src/components/studio/studio-navigation.ts')));
const origin='https://postiz.example.com';
test('canonical studio / deep links retain conversation and item',()=>{assert.equal(studioPath('/studio/?conversation=c1&item=i1&embedded=1#contenus',origin),'/studio?conversation=c1&item=i1#contenus');assert.equal(embeddedPath('/studio?conversation=c1&item=i1#discussion',origin),'/editorial/?conversation=c1&item=i1&embedded=1#discussion');assert.equal(embeddedPath('/studio/connect',origin),'/editorial/connect?embedded=1');});
test('studio URL values reject external paths malformed inputs',()=>{for(const input of [null,{},'', 'https://evil.com/studio','//evil.com/studio','/\\evil.com/studio','/launches','/studioevil','/editorial/','javascript:alert(1)','http://['])assert.equal(studioPath(input,origin),null,JSON.stringify(input));});
test('native link allowlist',()=>{for(const input of ['/launches','/media','/settings','/auth/login'])assert.equal(nativePath(input,origin),input);for(const input of ['/studio','/api/posts','//evil.com','/\\evil.com/settings','/auth/logout',null,{}])assert.equal(nativePath(input,origin),null);});
test('standalone bookmark upgrades into native shell retaining exact review',()=>{const h=harness(origin+'/editorial/?conversation=c1&item=i1#discussion',true);assert.deepEqual(h.changed,[{kind:'replace',value:'/studio?conversation=c1&item=i1#discussion'}]);});
test('connector bookmark upgrades too',()=>{const h=harness(origin+'/editorial/connect',true);assert.equal(h.changed[0].value,'/studio/connect');});
test('iframe is content only with ready handshake targeted same-origin',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');assert(h.classes.has('postiz-embedded'));h.document.dispatchEvent({type:'DOMContentLoaded'});assert.equal(h.posts[0].message.type,'ready');assert.equal(h.posts[0].message.path,'/studio#discussion');assert.equal(h.posts[0].origin,origin);assert.equal(h.changed.length,0);});
test('foreign origin and wrong window cannot drive child navigation/theme/action',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');for(const settings of [{origin:'https://evil.com'}, {source:{}}]){h.message({type:'route',path:'/editorial/?conversation=wrong'},settings);h.message({type:'theme',theme:'light',tokens:{'--new-btn-primary':'red'}},settings);}assert.equal(h.changed.length,0);assert.equal(Object.keys(h.props).length,0);});
test('unknown destinations and malformed URLs ignored without throw',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');for(const value of ['/launches','//evil.com/editorial/', 'https://evil.com/editorial/', 'http://['])assert.doesNotThrow(()=>h.message({type:'route',path:value}));assert.equal(h.changed.length,0);});
test('parent query navigation replaces child entry and preserves review link',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');h.message({type:'route',path:'/editorial/?conversation=c2&item=i2&embedded=1#discussion'});assert.equal(h.changed[0].kind,'replace');assert.equal(new URL(h.location.href).searchParams.get('item'),'i2');});
test('parent hash navigation replaces child entry and dispatches hashchange',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');let changes=0;h.win.addEventListener('hashchange',()=>changes++);h.message({type:'route',path:'/editorial/?embedded=1#semaine'});assert.equal(h.location.hash,'#semaine');assert.equal(h.changed[0].kind,'replaceState');assert.equal(changes,1);});
test('parent unchanged route causes no navigation',()=>{const h=harness(origin+'/editorial/?embedded=1&conversation=c1#discussion');h.message({type:'route',path:'/editorial/?conversation=c1&embedded=1#discussion'});assert.equal(h.changed.length,0);});
test('root slash aliases do not reload an unchanged child after a cached redirect',()=>{
  for(const [current,next] of [['/editorial','/editorial/'],['/editorial/','/editorial']]){
    const h=harness(origin+current+'?embedded=1&conversation=c1#contenus');
    for(let i=0;i<3;i++)h.message({type:'route',path:next+'?conversation=c1&embedded=1#contenus'});
    assert.equal(h.changed.length,0);
    assert.equal(new URL(h.location.href).pathname,current);
  }
});
test('root alias hash navigation retains the loaded document without a reload',()=>{
  const h=harness(origin+'/editorial?embedded=1&conversation=c1#discussion');
  let changes=0;h.win.addEventListener('hashchange',()=>changes++);
  h.message({type:'route',path:'/editorial/?conversation=c1&embedded=1#contenus'});
  assert.equal(h.changed.length,1);
  assert.equal(h.changed[0].kind,'replaceState');
  assert.equal(new URL(h.location.href).pathname,'/editorial');
  assert.equal(h.location.hash,'#contenus');
  assert.equal(changes,1);
});
test('root alias still reloads when the selected discussion changes',()=>{
  const h=harness(origin+'/editorial?embedded=1&conversation=c1#discussion');
  h.message({type:'route',path:'/editorial/?conversation=c2&embedded=1#discussion'});
  assert.equal(h.changed.length,1);
  assert.equal(h.changed[0].kind,'replace');
  assert.equal(new URL(h.location.href).searchParams.get('conversation'),'c2');
});
test('native links delegate to parent instead of nesting Postiz',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');for(const href of ['/launches','/media','/settings','/auth/login']){assert(h.click(href).prevented);assert.equal(h.posts.at(-1).message.type,'navigate');assert.equal(h.posts.at(-1).message.path,href);}assert.equal(h.changed.length,0);});
test('studio deep links delegate canonical route preserving query/hash',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');assert(h.click('/editorial/?conversation=c1&item=i1#discussion').prevented);assert.equal(h.posts.at(-1).message.path,'/studio?conversation=c1&item=i1#discussion');});
test('view hash links delegate parent to avoid child history entry',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');assert(h.click('#contenus').prevented);assert.equal(h.posts.at(-1).message.path,'/studio#contenus');assert.equal(h.changed.length,0);});
test('new-tab studio links open canonical native shell',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');const r=h.click('/editorial/?conversation=c1#discussion',{ctrlKey:true});assert.equal(r.prevented,false);assert.equal(r.link.href,origin+'/studio?conversation=c1#discussion');});
test('modifier click can reuse same anchor for normal navigation',()=>{
  for(const modifier of [{ctrlKey:true},{metaKey:true},{target:'_blank'}]) {
    const h=harness(origin+'/editorial/?embedded=1#discussion');
    const link=h.createLink('/editorial/?conversation=c1&item=i1#discussion',modifier.target||'');
    assert.equal(h.click(link,modifier).prevented,false);
    assert.equal(link.href,origin+'/studio?conversation=c1&item=i1#discussion');
    link.target='';
    assert.equal(h.click(link).prevented,true);
    assert.equal(h.posts.at(-1).message.path,'/studio?conversation=c1&item=i1#discussion');
    h.flushTimers();
    assert.equal(link.getAttribute('href'),'/editorial/?conversation=c1&item=i1#discussion');
    assert.equal(h.click(link).prevented,true);
    assert.equal(h.posts.at(-1).message.path,'/studio?conversation=c1&item=i1#discussion');
  }
});
test('modified hash link becomes relative again for next discussion',()=>{
  const h=harness(origin+'/editorial/?embedded=1&conversation=c1#discussion');
  const link=h.createLink('#strategie');h.click(link,{ctrlKey:true});
  assert.equal(link.href,origin+'/studio?conversation=c1#strategie');
  h.flushTimers();assert.equal(link.getAttribute('href'),'#strategie');
  h.location.replace('/editorial/?embedded=1&conversation=c2#discussion');
  assert.equal(h.click(link).prevented,true);
  assert.equal(h.posts.at(-1).message.path,'/studio?conversation=c2#strategie');
});
test('native connector link remains a connector route',()=>{
  const h=harness(origin+'/editorial/?embedded=1#discussion');
  const link=h.createLink('/editorial/connect');h.click(link,{ctrlKey:true});
  assert.equal(link.href,origin+'/studio/connect');
  assert(h.click(link).prevented);assert.equal(h.posts.at(-1).message.path,'/studio/connect');
});
test('equivalent query order has one canonical parent route',()=>{
  assert.equal(studioPath('/studio?item=i1&conversation=c1#discussion',origin),studioPath('/studio?conversation=c1&item=i1#discussion',origin));
});
test('skip link focuses content without changing studio route',()=>{
  const h=harness(origin+'/editorial/?embedded=1#semaine');let focused=false;
  h.elements.main={focus(){focused=true;}};
  assert(h.click('#main').prevented);assert(focused);assert.equal(h.location.hash,'#semaine');assert.equal(h.posts.length,0);
});
test('external editorial source links stay untouched',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');assert.equal(h.click('https://maker.example/product').prevented,false);assert.equal(h.posts.length,0);});
test('theme updates accept only known tokens from native shell',()=>{const h=harness(origin+'/editorial/?embedded=1#discussion');h.message({type:'theme',theme:'light',tokens:{'--new-btn-primary':'#612bd3','unknown':'red','--new-border':'x'.repeat(201)}});assert.equal(h.document.documentElement.dataset.theme,'light');assert.deepEqual(h.props,{'--new-btn-primary':'#612bd3'});});
let failed=0;for(const {name,run} of tests){try{await run();console.log('PASS '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}
console.log(`${tests.length-failed}/${tests.length} integration checks passed`);process.exitCode=failed?1:0;
})().catch(e=>{console.error(e);process.exitCode=1;});
