'use strict';
// Open the matching editor or review dialog from the contents index.
const contents = {
  filter:'all',
  source:'all',
  view:(typeof localStorage!=='undefined'&&localStorage.getItem('postiz-studio:contents-view'))||'list',
  items:[],
  lastData:null,
  total:0,
  nextOffset:0,
  sequence:0,
  loaded:false,
  busy:false,
  signature:'',
};
const contentFilters = [
  ['all','Tout'],['review','À valider'],['attention','À reprendre'],
  ['scheduled','Programmés'],['progress','En cours'],['published','Publiés'],['blog','Blog'],
];
const sourceLabels = {weekly:'Programme hebdomadaire',on_demand:'À la demande',companion:'Article associé'};
const templateLabels = {classic:'Classique',minimal:'Plein cadre',raw:'Photo brute',tip_card:'Carte conseil'};
function applyContentsView(view) {
  const mode=view==='grid'?'grid':'list';
  contents.view=mode;
  try{localStorage.setItem('postiz-studio:contents-view',mode);}catch{}
  $('contents-list')?.classList.toggle('is-grid',mode==='grid');
  $('contents-view-list')?.setAttribute('aria-pressed',mode==='list'?'true':'false');
  $('contents-view-grid')?.setAttribute('aria-pressed',mode==='grid'?'true':'false');
}
function visibleContents() {
  return contents.source==='all'?contents.items:contents.items.filter(item=>item.source===contents.source);
}
function setContentFilter(value) {
  if(contents.filter===value)return;
  contents.filter=value;
  document.querySelectorAll('.contents-filter').forEach(b=>b.setAttribute('aria-pressed',b.dataset.filter===value?'true':'false'));
  $('contents-filter-select').value=value;
  refreshContents(true);
}
for (const [value,label] of contentFilters) {
  const count=el('span',{class:'filter-count','aria-hidden':'true'},'');
  const button=el('button',{type:'button','aria-pressed':value===contents.filter?'true':'false',class:'contents-filter','data-filter':value},label,count);
  button.onclick=()=>setContentFilter(value);
  $('contents-filters').append(button);
  $('contents-filter-select').append(el('option',{value},label));
}
$('contents-filter-select').onchange=e=>setContentFilter(e.target.value);
function contentRow(item) {
  const row=el('article',{class:'content-row','data-item-id':item.id});
  const url=safeUrl(item.kind==='blog'?item.blog_media_url||item.media_url:item.media_url||item.blog_media_url);
  const thumbnail=url?el('img',{src:url,alt:'',loading:'lazy',width:72,height:72}):el('div',{class:'content-no-image'},item.kind==='blog'?'Article':'Visuel à créer');
  row.append(el('div',{class:'content-thumbnail'},thumbnail));
  const body=el('div',{class:'content-row-body'});
  const title=el('button',{class:'content-title',type:'button'},item.title||'Contenu en préparation');
  title.onclick=()=>openContent(item.id,title);
  body.append(el('h2',{},title));
  const templatePill=item.kind==='social'&&item.template&&item.template!=='classic'?el('span',{class:'v2-pill'},templateLabels[item.template]||item.template):null;
  const carouselPill=item.slide_count>=2?el('span',{class:'v2-pill accent'},`Carrousel · ${item.slide_count} pages`):null;
  const when=item.status==='managed'?'Date et contenu à consulter dans Postiz':dateLabel(item.scheduled_at);
  body.append(el('div',{class:'content-row-status'},badge(item.status),item.overdue?el('span',{class:'badge blocked'},'Date à revoir'):null,templatePill,carouselPill,
    el('span',{class:'content-when'},when),
    el('span',{class:'content-origin'},`${sourceLabels[item.source]||'Studio'} · ${item.kind==='blog'?'Blog':'Facebook + Instagram'}`)));
  if(item.warning || item.error)body.append(el('p',{class:'content-issue'},item.error||item.warning));
  const actions=el('div',{class:'content-row-actions'});
  let actionLabel='Voir le contenu';
  if(item.kind==='blog' && item.status==='published')actionLabel='Modifier l’article';
  if(item.status==='review')actionLabel='Relire et valider';
  if(['failed','blocked','rejected'].includes(item.status))actionLabel='Examiner et reprendre';
  const review=el('button',{class:'button '+(item.status==='review'?'primary':'secondary'),type:'button'},actionLabel);
  review.onclick=()=>openContent(item.id,review);
  actions.append(review);
  if(['review','rejected','blocked','failed','draft'].includes(item.status)) {
    const del=el('button',{class:'button content-delete',type:'button'},'Supprimer');
    let armTimer=null;
    del.onclick=async()=>{
      if(!del.dataset.armed) {
        del.dataset.armed='1';
        del.textContent='Confirmer ?';
        armTimer=setTimeout(()=>{delete del.dataset.armed;del.textContent='Supprimer';},4000);
        return;
      }
      clearTimeout(armTimer);
      del.disabled=true;
      del.textContent='Suppression…';
      try {
        await api(`/items/${encodeURIComponent(item.id)}/delete`,{revision:item.revision});
        refreshContents(true);
        if(typeof refresh==='function')refresh(true);
      } catch(error) {
        del.disabled=false;
        delete del.dataset.armed;
        del.textContent='Supprimer';
        $('contents-error').textContent=error.message;
        $('contents-error').hidden=false;
      }
    };
    actions.append(del);
  }
  if(['scheduled','managed'].includes(item.status))actions.append(el('a',{href:'/launches',class:'content-secondary-link'},'Calendrier Postiz'));
  else if(item.conversation_id)actions.append(el('a',{href:`/editorial/?conversation=${encodeURIComponent(item.conversation_id)}#discussion`,class:'content-secondary-link'},'Discussion d’origine'));
  else if(item.source==='weekly' && state.data?.weeks.some(w=>w.id===item.week_id)) {
    const week=el('a',{href:'#semaine',class:'content-secondary-link'},'Voir la semaine');
    week.onclick=()=>{if(state.data?.weeks.some(w=>w.id===item.week_id)){state.weekId=item.week_id;render();}};
    actions.append(week);
  }
  row.append(body,actions);return row;
}
async function openContent(id,button) {
  button.disabled=true;
  try {
    const item=await api(`/contents/${encodeURIComponent(id)}`);
    openItem(item,visibleContents());
  } catch(error) {
    $('contents-error').textContent=error.message;
    $('contents-error').hidden=false;
  } finally {button.disabled=false;}
}
function renderContents(data,append) {
  contents.lastData=data;
  contents.items=append?[...contents.items,...data.items.filter(item=>!contents.items.some(old=>old.id===item.id))]:data.items;
  contents.total=data.total;contents.nextOffset=data.offset+data.items.length;contents.loaded=true;
  for(const [value,label] of contentFilters) {
    const button=document.querySelector(`[data-filter="${value}"]`);
    const count=data.counts[value]??0;
    button.querySelector('.filter-count').textContent=count;
    button.setAttribute('aria-label',`${label} (${count})`);
    $('contents-filter-select').querySelector(`option[value="${value}"]`).textContent=`${label} (${count})`;
  }
  const visible=visibleContents();
  const signature=JSON.stringify([contents.filter,contents.source,contents.view,$('contents-search').value.trim(),visible]);
  if(signature!==contents.signature || !$('contents-list').childElementCount) {
    contents.signature=signature;
    if(!visible.length) {
      const hasFilter=contents.filter!=='all'||contents.source!=='all'||$('contents-search').value.trim();
      const empty=el('div',{class:'contents-empty'},el('h2',{},hasFilter?'Aucun résultat':'Aucun contenu dans cette vue'),el('p',{},hasFilter?'Essayez d’élargir les filtres ou un autre mot.':contents.filter==='review'?'Tout est relu pour le moment. Les prochains brouillons apparaîtront ici.':'Les contenus apparaîtront ici au fil de leur préparation.'));
      if(hasFilter) {
        const reset=el('button',{class:'button secondary',type:'button'},'Voir tous les contenus');
        reset.onclick=()=>{contents.filter='all';contents.source='all';$('contents-source').value='all';$('contents-search').value='';$('contents-filter-select').value='all';document.querySelectorAll('.contents-filter').forEach(b=>b.setAttribute('aria-pressed',b.dataset.filter==='all'?'true':'false'));refreshContents(true);};
        empty.append(reset);
      }
      $('contents-list').replaceChildren(empty);
    } else $('contents-list').replaceChildren(...visible.map(contentRow));
  }
  applyContentsView(contents.view);
  $('contents-count').textContent=contents.source==='all'
    ?`${data.total} contenu${data.total===1?'':'s'}${contents.items.length<data.total?` · ${contents.items.length} affichés`:''} · Heures de Paris`
    :`${visible.length} affiché${visible.length===1?'':'s'} (filtre source) sur ${data.total} · Heures de Paris`;
  $('contents-more').hidden=contents.nextOffset>=data.total;
}
async function refreshContents(force=false,append=false) {
  if($('contents-panel').hidden && !force)return;
  if(!force && (contents.busy || $('item-dialog').open || document.activeElement?.closest('.content-row')))return;
  const sequence=++contents.sequence;
  // Advance by consumed server rows, including duplicates if new items arrived
  // between pages. Otherwise the final row can be requested forever.
  const offset=append?contents.nextOffset:0;
  // Preserve the number of rows already displayed during automatic refreshes.
  const limit=append?30:Math.min(1000,Math.max(contents.source==='all'?30:120,contents.items.length));
  const query=new URLSearchParams({q:$('contents-search').value.trim(),filter:contents.filter,offset,limit});
  contents.busy=true;$('contents-list').setAttribute('aria-busy','true');
  $('contents-more').disabled=true;$('contents-refresh').disabled=true;
  try {
    const data=await api('/contents?'+query);
    if(sequence!==contents.sequence)return;
    renderContents(data,append);$('contents-error').hidden=true;
  } catch(error) {
    if(sequence!==contents.sequence)return;
    $('contents-error').textContent=error.message+(contents.loaded?' La dernière vue reste affichée.':'');
    $('contents-error').hidden=false;
    if(!contents.loaded)$('contents-count').textContent='Chargement interrompu. Vous pouvez réessayer.';
  } finally {
    if(sequence===contents.sequence){contents.busy=false;$('contents-list').setAttribute('aria-busy','false');$('contents-more').disabled=false;$('contents-refresh').disabled=false;}
  }
}
window.refreshContents=refreshContents;
let searchTimer;
$('contents-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>refreshContents(true),250);});
$('contents-source')?.addEventListener('change',e=>{
  contents.source=e.target.value||'all';
  if(contents.source!=='all' && contents.items.length<contents.total) { refreshContents(true); return; }
  if(contents.lastData) renderContents(contents.lastData,false);
  else refreshContents(true);
});
$('contents-view-list')?.addEventListener('click',()=>applyContentsView('list'));
$('contents-view-grid')?.addEventListener('click',()=>applyContentsView('grid'));
applyContentsView(contents.view);
$('contents-refresh').onclick=()=>refreshContents(true);
$('contents-more').onclick=()=>refreshContents(true,true);
if(location.hash==='#contenus')refreshContents();
setInterval(()=>{if(!document.hidden)refreshContents();},15000);
