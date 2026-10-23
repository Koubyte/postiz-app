'use strict';
const byId=id=>document.getElementById(id);
let connected=false;
async function connectionApi(data){
  const response=await fetch('/editorial/api/agent-connection',{method:data?'POST':'GET',credentials:'same-origin',headers:data?{'Content-Type':'application/json','X-Editorial-Action':'1'}:{},body:data?JSON.stringify(data):undefined});
  const result=await response.json();if(!response.ok)throw new Error(result.error||result.detail||'Connexion indisponible.');return result;
}
function fail(error){byId('connection-error').textContent=error.message;byId('connection-error').hidden=false;}
async function refresh(){
  const result=await connectionApi();connected=result.connected;
  byId('mcp-url').value=result.url;byId('bot-instructions').value=result.instructions;
  byId('connection-state').textContent=result.last_used_at?'Connecteur utilisé le '+new Date(result.last_used_at).toLocaleString('fr-FR',{timeZone:'Europe/Paris'})+' (Paris).':connected?'Clé créée. Ajoutez-la dans Grok Bot pour terminer la connexion.':'Aucune clé active.';
  byId('rotate-key').textContent=connected?'Remplacer la clé de connexion':'Créer une clé de connexion';
  ['copy-url','copy-instructions','rotate-key'].forEach(id=>byId(id).disabled=false);byId('revoke-key').disabled=!connected;
}
for(const [button,input] of [['copy-url','mcp-url'],['copy-key','mcp-key'],['copy-instructions','bot-instructions']]){
  byId(button).onclick=async()=>{try{await navigator.clipboard.writeText(byId(input).value);const previous=byId(button).textContent;byId(button).textContent='Copié';setTimeout(()=>byId(button).textContent=previous,1800);}catch{fail(new Error('Copie automatique indisponible : sélectionnez et copiez le champ.'));}};
}
byId('rotate-key').onclick=async()=>{
  if(connected&&!confirm('Remplacer la clé ? Il faudra mettre à jour le connecteur dans Grok Bot.'))return;
  byId('rotate-key').disabled=true;byId('connection-error').hidden=true;
  try{const result=await connectionApi({action:'rotate'});byId('mcp-key').value='Bearer '+result.token;byId('key-result').hidden=false;await refresh();}catch(e){fail(e);}finally{byId('rotate-key').disabled=false;}
};
byId('revoke-key').onclick=async()=>{
  if(!confirm('Révoquer l’accès de Grok Bot ?'))return;
  byId('revoke-key').disabled=true;
  try{await connectionApi({action:'revoke'});byId('mcp-key').value='';byId('key-result').hidden=true;await refresh();}catch(e){fail(e);byId('revoke-key').disabled=false;}
};
window.addEventListener('pagehide',()=>{byId('mcp-key').value='';byId('key-result').hidden=true;});
refresh().catch(fail);
setInterval(()=>{if(!document.hidden)refresh().catch(fail);},15000);
