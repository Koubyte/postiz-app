'use strict';
// Shared Postiz session and the same exact-version review dialog as weekly posts.
const chat = { id: null, data: null, photos: [], loading: false, sending: false, signature: '', recorder: null, stream: null, voiceBusy: false, timer: null };
const chatError = (text='') => { $('chat-error').textContent=text; $('chat-error').hidden=!text; };
function chatMode() {
  const active=location.hash==='#discussion';
  $('chat-panel').hidden=!active; $('weekly-panel').hidden=active;
  $('tab-chat').setAttribute('aria-current',active?'page':'false');
  $('tab-week').setAttribute('aria-current',active?'false':'page');
  if(active) refreshChat();
}
async function loadDiscussions() {
  const result=await api('/conversations');
  const current=chat.id;
  $('chat-history').replaceChildren(...result.conversations.map(c=>el('option',{value:c.id},c.title)));
  if(!chat.id) chat.id=result.conversations[0]?.id || null;
  $('chat-history').value=chat.id || '';
  $('chat-mic').disabled=!result.voice || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder;
  if($('chat-mic').disabled) $('chat-voice-status').textContent='La dictée n’est pas disponible dans ce navigateur. Vous pouvez écrire votre brief.';
  return current!==chat.id;
}
async function ensureDiscussion() {
  if(!chat.id) { const r=await api('/conversations',{});chat.id=r.id;await loadDiscussions(); }
  return chat.id;
}
function renderAttachments() {
  $('chat-attachments').replaceChildren(...chat.photos.map(p=>el('div',{class:'chat-photo-chip'},el('img',{src:p.url,alt:p.name}),el('span',{},p.name),el('button',{type:'button','aria-label':'Retirer '+p.name,onclick:()=>{chat.photos=chat.photos.filter(x=>x.id!==p.id);renderAttachments();}},'×'))));
}
function proposalCard(msg,p,index) {
  const accepted=msg.accepted[String(index)];
  const box=el('section',{class:'chat-proposal'},el('h4',{},p.title),el('p',{},p.angle),el('p',{class:'hint'},'Décor : '+p.scene));
  const photos=(chat.data.photos||[]).filter(photo=>p.photo_ids.includes(photo.id));
  if(photos.length) box.append(el('div',{class:'chat-attachments'},...photos.map(photo=>el('img',{src:photo.url,alt:photo.name,class:'proposal-photo'}))));
  if(accepted) {box.append(el('p',{class:'badge review'},'Préparation demandée · retrouvez le post dans vos contenus'));return box;}
  const when=field('Horaire souhaité · Paris','input',parisInput(p.scheduled_at),{type:'datetime-local',required:true});
  const price=field('Prix TTC · vide pour masquer','input',p.price??'',{type:'number',min:'0.01',max:'99999',step:'0.01',placeholder:'Sans prix'});
  box.append(when.label,price.label,el('p',{class:'hint'},'Le créneau sera décalé si nécessaire pour garder 2 heures entre deux sujets. L’horaire retenu figurera sur le brouillon avant validation.'));
  const prepare=el('button',{type:'button',class:'button primary'},msg.target?'Préparer cette correction':'Préparer ce post et son visuel');
  prepare.onclick=async()=>{
    prepare.disabled=true;chatError();
    try {
      await api(`/conversations/${chat.id}/proposals/${msg.id}`,{index,scheduled_at:parisIso(when.input.value),price:price.input.value===''?null:Number(price.input.value)});
      chat.signature='';await refreshChat();toast('Préparation lancée. Vous validerez le contenu fini avant publication.');
    } catch(e){chatError(e.message);prepare.disabled=false;}
  };
  box.append(prepare);return box;
}
function renderChat() {
  const data=chat.data;
  const signature=JSON.stringify(data);
  if(signature===chat.signature)return;
  // Polling never destroys a date/price the owner is editing in a proposal.
  if(document.activeElement?.closest('.chat-proposal'))return;
  chat.signature=signature;
  const log=$('chat-messages');const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<100;
  log.replaceChildren();
  if(!data.messages.length)log.append(el('div',{class:'chat-welcome'},el('h3',{},'Racontez-moi ce que vous voulez partager.'),el('p',{},'Donnez un nom, un EAN ou un lien. Ajoutez vos photos si vous en avez. Vous pouvez demander plusieurs posts dans le même message.'),el('p',{class:'hint'},'Par exemple : « Le Hailun HD300 vient d’arriver en magasin. Fais un post pour cet après-midi, sans afficher de prix. »')));
  for(const msg of data.messages) {
    const bubble=el('article',{class:'chat-bubble '+msg.role},el('strong',{},msg.role==='user'?'Vous':'Assistant Planète Laser'));
    const body=el('div',{class:'chat-message-text'});appendInline(body,msg.body);bubble.append(body);
    for(const id of msg.attachments) {const photo=data.photos.find(p=>p.id===id);if(photo)bubble.append(el('img',{src:photo.url,alt:photo.name,class:'proposal-photo'}));}
    if(msg.target)bubble.append(el('p',{class:'hint'},'Correction du post sélectionné uniquement.'));
    if(['queued','running'].includes(msg.status))bubble.append(el('p',{class:'hint'},state.data?.paused?'Studio suspendu : réponse en attente.':'L’IA prépare sa réponse…'));
    if(msg.status==='failed') {
      const retry=el('button',{class:'button secondary',type:'button'},'Réessayer la réponse');
      retry.onclick=async()=>{retry.disabled=true;try{await api(`/conversations/${chat.id}/retry/${msg.id}`,{});await refreshChat();}catch(e){chatError(e.message);retry.disabled=false;}};
      bubble.append(el('p',{class:'notice error'},msg.error||'La réponse a échoué.'),retry);
    }
    msg.proposals.forEach((p,i)=>bubble.append(proposalCard(msg,p,i)));
    log.append(bubble);
  }
  if(nearBottom)log.scrollTop=log.scrollHeight;
  const target=$('chat-target');const previous=target.value;
  target.replaceChildren(el('option',{value:''},'De nouveaux posts / une question'),...data.items.filter(i=>['review','rejected','failed','blocked'].includes(i.status)).map((i,n)=>el('option',{value:i.id},'Corriger : '+(i.content?.title||'Post '+(n+1)))));
  target.value=[...target.options].some(o=>o.value===previous)?previous:'';
  const cards=data.items.map((item,n)=>{
    const card=el('article',{class:'chat-result'},badge(item.status),el('h4',{},item.content.title||`Post ${n+1} · préparation`),el('p',{class:'hint'},dateLabel(item.scheduled_at)));
    if(item.media_url)card.append(el('img',{src:item.media_url,alt:item.content.alt||item.content.title,loading:'lazy'}));
    if(item.error)card.append(el('p',{class:'notice error'},item.error));
    const view=el('button',{class:'button secondary',type:'button',onclick:()=>openItem(item)},item.status==='review'?'Relire et valider':'Voir le contenu');
    card.append(view);
    if(['review','rejected','failed','blocked'].includes(item.status))card.append(el('button',{class:'button secondary',type:'button',onclick:()=>{$('chat-target').value=item.id;$('chat-text').focus();$('chat-form').scrollIntoView({behavior:'smooth',block:'center'});}},'Demander une modification'));
    return card;
  });
  $('chat-items').replaceChildren(...(cards.length?cards:[el('p',{class:'hint'},'Les posts que vous préparez dans cette discussion apparaîtront ici. Le planning hebdomadaire reste dans son onglet.') ]));
}
async function refreshChat() {
  if(chat.loading)return;
  chat.loading=true;
  try {
    if(!$('chat-history').options.length)await loadDiscussions();
    if(chat.id)chat.data=await api(`/conversations/${chat.id}`);
    else chat.data={messages:[],photos:[],items:[]};
    renderChat();
  } catch(e){chatError(e.message);}finally{chat.loading=false;}
}
window.refreshChat=refreshChat;
window.chatItem=id=>chat.data?.items.find(i=>i.id===id);
$('chat-new').onclick=async()=>{
  if(chat.sending||chat.voiceBusy||chat.recorder)return;
  if(($('chat-text').value||chat.photos.length)&&!confirm('Ouvrir une nouvelle discussion sans envoyer ce brief ?'))return;
  try {const r=await api('/conversations',{});chat.id=r.id;chat.photos=[];chat.signature='';$('chat-text').value='';renderAttachments();await loadDiscussions();await refreshChat();chatError();}catch(e){chatError(e.message);}
};
$('chat-history').onchange=async e=>{
  if(chat.sending||chat.voiceBusy||chat.recorder){e.target.value=chat.id;return;}
  if(($('chat-text').value||chat.photos.length)&&!confirm('Changer de discussion sans envoyer ce brief ?')){e.target.value=chat.id;return;}
  chat.id=e.target.value;chat.photos=[];chat.signature='';$('chat-text').value='';renderAttachments();chatError();await refreshChat();
};
$('chat-form').onsubmit=async e=>{
  e.preventDefault();if(chat.sending||chat.voiceBusy||chat.recorder)return;
  const text=$('chat-text').value.trim();if(!text){chatError('Écrivez ou dictez votre brief.');return;}
  chat.sending=true;$('chat-send').disabled=true;chatError();
  try {
    const id=await ensureDiscussion();
    // Keep the nonce on network failure: retrying cannot enqueue duplicate turns.
    const payload={text,attachments:chat.photos.map(p=>p.id),target:$('chat-target').value||null};
    const key=JSON.stringify(payload);
    if(chat.pendingKey!==key){chat.pendingKey=key;chat.pendingId=crypto.randomUUID();}
    await api(`/conversations/${id}/messages`,{...payload,id:chat.pendingId});
    chat.pendingKey=null;chat.photos=[];$('chat-text').value='';renderAttachments();
    await loadDiscussions();await refreshChat();$('chat-messages').scrollTop=$('chat-messages').scrollHeight;
  }catch(e){chatError(e.message);}finally{chat.sending=false;$('chat-send').disabled=false;}
};
async function upload(path,bytes,headers={}) {
  const r=await fetch('/editorial/api'+path,{method:'POST',credentials:'same-origin',headers:{'X-Editorial-Action':'1',...headers},body:bytes});
  let data={};try{data=await r.json();}catch{}
  if(!r.ok)throw new Error(data.detail||data.error||'Le fichier n’a pas pu être traité.');return data;
}
$('chat-photo').onclick=()=>{if(!chat.sending)$('chat-file').click();};
$('chat-file').onchange=async e=>{
  const files=[...e.target.files];e.target.value='';if(!files.length)return;
  if(chat.photos.length+files.length>3){chatError('Joignez au maximum trois photos par message.');return;}
  $('chat-photo').disabled=true;$('chat-send').disabled=true;chat.sending=true;chatError();
  try {
    const id=await ensureDiscussion();
    for(const file of files){if(file.size>12*1024*1024)throw new Error('Chaque photo doit faire moins de 12 Mo.');const photo=await upload(`/conversations/${id}/photos`,file,{'X-File-Name':encodeURIComponent(file.name)});chat.photos.push(photo);renderAttachments();}
  } catch(e){chatError(e.message);}finally{$('chat-photo').disabled=false;$('chat-send').disabled=false;chat.sending=false;}
};
function stopRecording() {if(chat.recorder?.state==='recording')chat.recorder.stop();}
$('chat-mic').onclick=async()=>{
  if(chat.recorder){stopRecording();return;}
  if(chat.voiceBusy||chat.sending)return;
  chat.voiceBusy=true;chatError();$('chat-mic').disabled=true;
  try {
    chat.stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=['audio/webm;codecs=opus','audio/mp4','audio/webm'].find(t=>MediaRecorder.isTypeSupported(t));
    const recorder=new MediaRecorder(chat.stream,mime?{mimeType:mime}:{});chat.recorder=recorder;
    const chunks=[];let bytes=0;let failed=false;
    recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);bytes+=e.data.size;if(bytes>11*1024*1024){failed=true;stopRecording();}}};
    recorder.onerror=()=>{failed=true;stopRecording();};
    recorder.onstop=async()=>{
      clearInterval(chat.timer);chat.stream?.getTracks().forEach(t=>t.stop());chat.stream=null;chat.recorder=null;
      $('chat-mic').disabled=true;$('chat-mic').textContent='Transcription…';$('chat-mic').setAttribute('aria-pressed','false');
      $('chat-voice-status').textContent='Transcription sur votre serveur. Le texte apparaîtra ici avant tout envoi.';
      try {
        if(failed||!chunks.length)throw new Error('Enregistrement interrompu ou trop volumineux. Réessayez avec un message plus court.');
        const result=await upload('/transcribe',new Blob(chunks,{type:recorder.mimeType}));
        if(!result.text)throw new Error('Aucune parole détectée. Réessayez près du micro.');
        const text=$('chat-text');text.value=[text.value.trim(),result.text].filter(Boolean).join('\n');text.focus();
        $('chat-voice-status').textContent='Transcription prête. Vérifiez les noms de produits et les prix, puis envoyez votre brief.';
      }catch(e){chatError(e.message);$('chat-voice-status').textContent='Vous pouvez réessayer ou écrire votre brief.';}
      finally{chat.voiceBusy=false;$('chat-mic').disabled=false;$('chat-mic').textContent='🎙 Dicter';$('chat-send').disabled=false;}
    };
    recorder.start(1000);const start=Date.now();
    $('chat-mic').disabled=false;$('chat-mic').textContent='■ Terminer la dictée';$('chat-mic').setAttribute('aria-pressed','true');$('chat-send').disabled=true;
    chat.timer=setInterval(()=>{const seconds=Math.floor((Date.now()-start)/1000);$('chat-voice-status').textContent=`Enregistrement · ${seconds} s / 180 s`;if(seconds>=175)stopRecording();},500);
  } catch(e){chat.stream?.getTracks().forEach(t=>t.stop());chat.stream=null;chat.recorder=null;chat.voiceBusy=false;$('chat-mic').disabled=false;chatError(e.name==='NotAllowedError'?'Autorisez le microphone dans votre navigateur, ou écrivez votre brief.':'Le microphone n’est pas disponible. Vous pouvez écrire votre brief.');}
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopRecording();});
window.addEventListener('pagehide',()=>{stopRecording();chat.stream?.getTracks().forEach(t=>t.stop());});
window.addEventListener('beforeunload',e=>{if($('chat-text').value||chat.photos.length||chat.voiceBusy){e.preventDefault();e.returnValue='';}});
window.addEventListener('hashchange',chatMode);
chatMode();
setInterval(()=>{if(!document.hidden&&location.hash==='#discussion')refreshChat();},5000);
