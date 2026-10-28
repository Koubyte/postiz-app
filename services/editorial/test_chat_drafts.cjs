'use strict';
const assert=require('node:assert/strict');
// Tests use authenticated IDs from fixtures and never call Postiz.
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'static/chat.js'),'utf8');
function harness(initial={}, options={}){
 const rows=new Map();const listeners={};const elements={'chat-text':{value:''},'chat-target':{value:'',options:[{value:''},{value:'approved-target'}],selectedOptions:[{textContent:'Target'}]},'chat-correction':{},'chat-correction-label':{}};
 const chat={id:'c1',ownerId:'owner1',photos:[],...initial};let current=new URL('https://postiz.example.com/editorial/?embedded=1#discussion');const messages=[];
 const context={chat,$:id=>elements[id],sessionStorage:{getItem:key=>rows.get(key)||null,setItem:(key,value)=>{if(options.storageFailure)throw Error('Quota exceeded');rows.set(key,value);},removeItem:key=>{if(options.storageFailure)throw Error('Storage unavailable');rows.delete(key);}},JSON,URL,history:{replaceState(data,title,value){current=new URL(value,current);}},location:{get href(){return current.href;}},document:{documentElement:{classList:{contains:name=>name==='postiz-embedded'&&options.embedded!==false}}},window:{addEventListener(type,fn){listeners[type]=fn;},postizStudioRouteChanged(){messages.push(current.href);}},api:async()=>({id:'c2'}),loadDiscussions:async()=>{},renderAttachments(){context.saveChatDraft();}};
 vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('function draftKey()'),source.indexOf('function chatMode()')),context);
 vm.runInContext(source.slice(source.indexOf('async function ensureDiscussion()'),source.indexOf('function renderAttachments()')),context);
 vm.runInContext(source.slice(source.indexOf("window.addEventListener('beforeunload'"),source.indexOf("$('chat-text').addEventListener('input'")),context);
 return {chat,elements,rows,context,messages,url:()=>current,
   beforeUnload(){let prevented=false;const event={preventDefault(){prevented=true;}};listeners.beforeunload(event);return {prevented,returnValue:event.returnValue};}
 };
}
const tests=[];const test=(name,fn)=>tests.push({name,fn});
test('new unread key is not erased before restore',()=>{const h=harness();const key=h.context.draftKey();h.rows.set(key,'{"text":"Saved"}');h.context.saveChatDraft();assert.equal(h.rows.get(key),'{"text":"Saved"}');});
test('restore scoped to authenticated owner',()=>{const h=harness();h.rows.set('postiz-studio:draft:owner2:c1','{"text":"Other private owner draft"}');h.context.restoreChatDraft();assert.equal(h.elements['chat-text'].value,'');assert(!h.rows.has('postiz-studio:draft:owner1:c1'));});
test('restore own text, only authenticated photos, current correction and retry nonce',()=>{const h=harness({data:{photos:[{id:'valid'},{id:'other'}]}});h.rows.set(h.context.draftKey(),JSON.stringify({text:'Mon piano',photos:['valid','unknown'],target:'approved-target',pendingId:'nonce1',pendingKey:'payload1'}));h.context.restoreChatDraft();assert.equal(h.elements['chat-text'].value,'Mon piano');assert.deepEqual(h.chat.photos,[{id:'valid'}]);assert.equal(h.elements['chat-target'].value,'approved-target');assert.equal(h.chat.pendingId,'nonce1');assert.equal(h.chat.pendingKey,'payload1');});
test('unknown correction does not revive an obsolete post target',()=>{const h=harness();h.rows.set(h.context.draftKey(),JSON.stringify({text:'Brief',photos:[],target:'oldpost'}));h.context.restoreChatDraft();assert.equal(h.elements['chat-target'].value,'');});
test('save clear removes only current own draft',()=>{const h=harness({draftLoadedKey:'postiz-studio:draft:owner1:c1'});h.rows.set(h.context.draftKey(),'old');h.rows.set('postiz-studio:draft:owner2:c1','other');h.context.saveChatDraft();assert(!h.rows.has(h.context.draftKey()));assert.equal(h.rows.get('postiz-studio:draft:owner2:c1'),'other');});
test('new conversation migrates initial draft then persists first send nonce',async()=>{const h=harness({id:null,draftLoadedKey:'postiz-studio:draft:owner1:new'});h.elements['chat-text'].value='Premier brief';h.context.saveChatDraft();await h.context.ensureDiscussion();assert.equal(h.chat.id,'c2');assert.equal(h.chat.draftLoadedKey,'postiz-studio:draft:owner1:c2');assert(!h.rows.has('postiz-studio:draft:owner1:new'));h.chat.pendingId='firstsend';h.chat.pendingKey='payload';h.chat.photos=[{id:'firstphoto'}];h.context.saveChatDraft();const saved=JSON.parse(h.rows.get('postiz-studio:draft:owner1:c2'));assert.equal(saved.pendingId,'firstsend');assert.deepEqual(saved.photos,['firstphoto']);assert.equal(h.url().searchParams.get('conversation'),'c2');});
test('discussion sync removes stale item and retains embed context',()=>{const h=harness();h.context.syncChatLocation();assert.equal(h.url().searchParams.get('conversation'),'c1');assert.equal(h.url().searchParams.get('embedded'),'1');assert.equal(h.url().searchParams.get('item'),null);assert.equal(h.url().hash,'#discussion');assert.equal(h.messages.length,1);});
test('saved embedded brief navigates without redundant prompt',()=>{
 const h=harness({draftLoadedKey:'postiz-studio:draft:owner1:c1'});h.elements['chat-text'].value='Brief conservé';
 assert.equal(h.beforeUnload().prevented,false);
 assert.equal(JSON.parse(h.rows.get(h.context.draftKey())).text,'Brief conservé');
});
test('busy send, dictation or recording still prompts before unload',()=>{
 for(const busy of [{sending:true},{voiceBusy:true},{recorder:{}}]){
  const h=harness({draftLoadedKey:'postiz-studio:draft:owner1:c1',...busy});h.elements['chat-text'].value='Brief';
  const event=h.beforeUnload();assert.equal(event.prevented,true);assert.equal(event.returnValue,'');
 }
});
test('failed browser storage still prompts and reports unsaved draft',()=>{
 const h=harness({draftLoadedKey:'postiz-studio:draft:owner1:c1'},{storageFailure:true});h.elements['chat-text'].value='À conserver';
 assert.equal(h.context.saveChatDraft(),false);assert.equal(h.beforeUnload().prevented,true);
});
test('unknown owner or unread draft cannot suppress leave prompt',()=>{
 for(const state of [{ownerId:null},{draftLoadedKey:undefined}]){
  const h=harness(state);h.elements['chat-text'].value='Brief';assert.equal(h.context.saveChatDraft(),false);assert.equal(h.beforeUnload().prevented,true);
 }
});
test('standalone page keeps unsent-brief warning',()=>{
 const h=harness({draftLoadedKey:'postiz-studio:draft:owner1:c1'},{embedded:false});h.elements['chat-text'].value='Brief';assert.equal(h.beforeUnload().prevented,true);
});
test('idle empty composer does not prompt',()=>{const h=harness();assert.equal(h.beforeUnload().prevented,false);});
(async()=>{let failed=0;for(const {name,fn} of tests){try{await fn();console.log('PASS '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}console.log(`${tests.length-failed}/${tests.length} draft checks passed`);process.exitCode=failed?1:0;})();
