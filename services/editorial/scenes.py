"""Choose varied, product-compatible photographic directions before rendering."""
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from store import Conflict, dumps, now, uid

VERSION='pl-scenes-v3'
# How the product is shown. Rotated from post to post so the feed stays alive.
STAGINGS={
    'store':'Dans le magasin : le produit posé ou installé dans un vrai lieu de Planète Laser (canapé, mur, stand), d’après la photo du lieu',
    'in_use':'En main : une personne joue ou utilise le produit, geste juste, personne générique non identifiable',
    'lifestyle':'En situation : le produit chez un musicien ou dans son lieu d’usage (salon, répète, scène, home studio)',
    'detail':'Gros plan : une caractéristique visible du produit, profondeur de champ courte',
}
MAX_SCENES=40
# Where the camera stands in the real place. The shop photo gives the room, not the framing:
# the image model walks around it and extrapolates what the photo does not show.
CAMERAS={
    'front':'Face au mobilier, à hauteur de poitrine, recadré plus près que la photo',
    'left':'Trois quarts gauche : la caméra a contourné le mobilier par la gauche, le décor glisse en perspective',
    'right':'Trois quarts droite : la caméra a contourné le mobilier par la droite, le décor glisse en perspective',
    'low':'Contre-plongée au ras du tapis, grand angle : le produit domine, le décor monte derrière lui',
    'high':'Plongée légère depuis une personne debout : on voit le produit posé et le motif du tapis',
    'close':'Plan serré sur le produit, le lieu reconnaissable mais flou en arrière-plan',
    'wide':'Plan large reculé qui montre davantage le magasin autour (murs, rayons, vitrine), prolongé de façon cohérente',
    'reverse':'Contrechamp : la caméra se place à côté du mobilier et regarde vers l’autre côté de la pièce, reconstruit de façon plausible à partir de ce que montre la photo',
}
CAMERAS_BY_STAGING={
    'store':['left','right','low','high','wide','reverse','front'],
    'in_use':['left','right','front','low','wide'],
    'detail':['close','low','high'],
}
SETTINGS={
    'store':'Un vrai lieu du magasin Planète Laser, d’après la photo du lieu fournie',
    'home':'Intérieur de vie : salon, pièce de musique, appartement',
    'teaching':'Salle de cours ou espace pédagogique',
    'rehearsal':'Salle de répétition, préparation collective',
    'stage':'Scène pendant installation ou balance, sans faux concert annoncé',
    'recording':'Cabine ou salle de prise de son',
    'broadcast':'Espace podcast, radio ou création de contenu',
    'creative_desk':'Poste de composition ou de production musicale',
    'venue':'Salle événementielle, installation sono ou lumière cohérente',
    'backstage':'Coulisses ou préparation de matériel avant utilisation',
    'workbench':'Espace de réglage, entretien ou préparation technique',
    'listening':'Pièce d’écoute ou espace de démonstration privé',
    'architecture':'Espace architectural intérieur adapté à l’usage réel du produit',
}
LIGHTS={'daylight','soft_neutral','contrasted','stage_colour','evening_warm'}
ANGLES={'front_context','three_quarter','side_context','elevated_context'}
RULES='''La charte commune vient du logo, de la typographie et de l’habillage ajoutés par le logiciel, PAS d’un décor identique. Variez les lieux, matériaux, lumières et cadrages. Aucun studio chaleureux / bois / bokeh / accent vert obligatoire. Le produit reste entier, fidèle et clairement mis en situation, jamais détouré ou isolé sur fond blanc. Choisissez un usage crédible pour ce modèle précis : un piano ne devient pas un appareil DJ, une enceinte de studio ne devient pas une enceinte de festival, un micro de prise de son ne devient pas arbitrairement un micro de scène. Ne suggérez aucune résistance à l’eau, utilisation extérieure, compatibilité, accessoire fourni ou capacité technique non documentée. Ne représentez notre magasin qu’à partir d’une photo réelle du lieu jointe : la scène se déroule alors dans CE lieu (architecture, mobilier, matières et lumière reconnaissables). Aucun client, employé ou événement réel reconnaissable. Une personne n’apparaît que pour la mise en scène « en main » : personne générique, non identifiable, au geste techniquement juste, jamais une célébrité. Les références produit déterminent le modèle et ses couleurs, pas leur arrière-plan.'''


def _fold(text):
    return unicodedata.normalize('NFKD',str(text or '')).encode('ascii','ignore').decode().lower()


def _scene_row(row):
    scene=dict(row);scene['tags']=json.loads(scene['tags']);scene['active']=bool(scene['active'])
    scene['url']='/editorial/media/'+scene['filename']
    return scene


def list_scenes(store,include_inactive=True,db=None):
    """Store photos with their recent use, most recent first."""
    if db is None:
        with store.db() as conn:return list_scenes(store,include_inactive,conn)
    usage=Counter();last={}
    for (body,) in db.execute('SELECT body FROM visual_directions ORDER BY rowid DESC LIMIT 60'):
        direction=json.loads(body);scene_id=direction.get('store_scene_id')
        if scene_id:
            usage[scene_id]+=1;last.setdefault(scene_id,direction.get('created_at'))
    rows=db.execute('SELECT * FROM store_scenes'+('' if include_inactive else ' WHERE active=1')+' ORDER BY created DESC').fetchall()
    return [{**_scene_row(r),'recent_uses':usage[r['id']],'last_used':last.get(r['id'])} for r in rows]


def _checked_meta(label,description,tags):
    if not isinstance(label,str) or not label.strip() or len(label.strip())>80:raise Conflict('Donnez un nom court au lieu (80 caractères maximum).')
    if not isinstance(description,str) or len(description)>600:raise Conflict('Description du lieu trop longue (600 caractères maximum).')
    if not isinstance(tags,(list,tuple)) or len(tags)>12 or any(not isinstance(t,str) or not t.strip() or len(t)>40 for t in tags):raise Conflict('Jusqu’à 12 usages de 40 caractères (ex. guitares, claviers, sono).')
    return label.strip(),description.strip(),list(dict.fromkeys(t.strip().lower() for t in tags))


def add_scene(store,raw,label,description='',tags=(),actor='owner'):
    """Normalise and keep one real photo of the shop, used as a location reference for visuals."""
    from PIL import Image
    from media import _decode
    from pillow_heif import register_heif_opener
    label,description,tags=_checked_meta(label,description,tags)
    register_heif_opener()
    image=_decode(raw).convert('RGB')
    if min(image.size)<600:raise Conflict('Photo du lieu trop petite : 600 pixels minimum de côté.')
    image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
    buffer=io.BytesIO();image.save(buffer,'JPEG',quality=90);data=buffer.getvalue()
    digest=hashlib.sha256(data).hexdigest();scene_id=uid();filename='scene-'+scene_id+'.jpg'
    with store.db() as db:
        old=db.execute('SELECT * FROM store_scenes WHERE sha256=?',(digest,)).fetchone()
        if old:return {**_scene_row(old),'duplicate':True}
        if db.execute('SELECT count(*) FROM store_scenes').fetchone()[0]>=MAX_SCENES:raise Conflict(f'La bibliothèque contient déjà {MAX_SCENES} lieux : supprimez-en un avant d’en ajouter.')
        path=store.root/'media';path.mkdir(exist_ok=True);(path/filename).write_bytes(data)
        db.execute('INSERT INTO store_scenes(id,label,description,tags,filename,sha256,active,created,actor) VALUES(?,?,?,?,?,?,1,?,?)',(scene_id,label,description,dumps(tags),filename,digest,now(),actor))
        store.event(db,'Photo du magasin ajoutée : '+label,actor)
        return _scene_row(db.execute('SELECT * FROM store_scenes WHERE id=?',(scene_id,)).fetchone())


def update_scene(store,scene_id,data,actor='owner'):
    if not isinstance(data,dict):raise Conflict('Modification du lieu invalide.')
    with store.db() as db:
        row=db.execute('SELECT * FROM store_scenes WHERE id=?',(scene_id,)).fetchone()
        if not row:raise Conflict('Lieu introuvable.')
        current=_scene_row(row)
        label,description,tags=_checked_meta(data.get('label',current['label']),data.get('description',current['description']),data.get('tags',current['tags']))
        active=data.get('active',current['active'])
        if type(active) is not bool:raise Conflict('Choisissez actif ou en pause.')
        db.execute('UPDATE store_scenes SET label=?,description=?,tags=?,active=? WHERE id=?',(label,description,dumps(tags),int(active),scene_id))
        store.event(db,'Lieu du magasin modifié : '+label,actor)
        return _scene_row(db.execute('SELECT * FROM store_scenes WHERE id=?',(scene_id,)).fetchone())


def delete_scene(store,scene_id,actor='owner'):
    with store.db() as db:
        row=db.execute('SELECT * FROM store_scenes WHERE id=?',(scene_id,)).fetchone()
        if not row:raise Conflict('Lieu introuvable.')
        db.execute('DELETE FROM store_scenes WHERE id=?',(scene_id,))
        store.event(db,'Lieu du magasin supprimé : '+row['label'],actor)
    (store.root/'media'/row['filename']).unlink(missing_ok=True)
    return {'ok':True}


def scene_file(store,scene_id):
    """Exact bytes of an active store photo, checked against the stored hash."""
    with store.db() as db:
        row=db.execute('SELECT * FROM store_scenes WHERE id=? AND active=1',(scene_id,)).fetchone()
    if not row:raise Conflict('Ce lieu du magasin n’est plus disponible.')
    data=(store.root/'media'/row['filename']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Conflict('La photo du lieu a changé.')
    return _scene_row(row),data


def checked_staging(store,staging=None,store_scene_id=None,db=None):
    """Validate an explicit choice from Grok or the owner ('auto' or empty clears it)."""
    if db is None:
        with store.db() as conn:return checked_staging(store,staging,store_scene_id,conn)
    staging=None if staging in (None,'','auto') else staging
    store_scene_id=None if store_scene_id in (None,'','auto') else store_scene_id
    if staging is not None and staging not in STAGINGS:raise Conflict('Mise en scène inconnue : store, in_use, lifestyle, detail ou auto.')
    if store_scene_id is not None:
        if not isinstance(store_scene_id,str):raise Conflict('Lieu du magasin invalide.')
        if not db.execute('SELECT 1 FROM store_scenes WHERE id=? AND active=1',(store_scene_id,)).fetchone():raise Conflict('Ce lieu du magasin est introuvable ou en pause.')
        if staging=='lifestyle':raise Conflict('La mise en scène « en situation » se passe hors magasin : choisissez store, in_use ou detail avec un lieu.')
    if staging=='store' and store_scene_id is None:
        if not db.execute('SELECT 1 FROM store_scenes WHERE active=1').fetchone():raise Conflict('Ajoutez d’abord une photo du magasin pour la mise en scène « dans le magasin ».')
    return staging,store_scene_id


def plan_staging(store,item,brief,product,history):
    """Pick how and where the product is shown, rotating away from recent visuals."""
    content=item['content']
    staging=content.get('staging') or brief.get('staging')
    forced_scene=content.get('store_scene_id') or brief.get('store_scene_id')
    scenes=list_scenes(store,include_inactive=False)
    matched=set()
    if forced_scene:
        eligible=[s for s in scenes if s['id']==forced_scene]
        if not eligible:raise Conflict('Le lieu du magasin choisi est introuvable ou en pause.')
    else:
        # The catalogue URL carries the category (…/guitares-basses/…, …/pianos-claviers/…), titles often do not.
        subject=_fold(' '.join(str(x) for x in ((product or {}).get('title'),(product or {}).get('category'),(product or {}).get('url'),content.get('title'),brief.get('title'),brief.get('angle')) if x))
        # A place suits the product when one of its uses appears in the subject; untagged or 'tous' places suit everything.
        matched={s['id'] for s in scenes if any(_fold(t).rstrip('sx') in subject for t in s['tags'] if len(_fold(t).rstrip('sx'))>=2)}
        eligible=[s for s in scenes if s['id'] in matched or not s['tags'] or 'tous' in s['tags']]
    allowed=['store','in_use','lifestyle','detail'] if product else ['store','in_use','lifestyle']
    if not eligible:allowed=[a for a in allowed if a!='store']
    if staging not in allowed:
        recent=[h.get('staging') for h in history]
        staging=min(allowed,key=lambda a:(a in recent[:2],recent.count(a),allowed.index(a)))
    scene=None
    if eligible and (forced_scene or staging!='lifestyle'):
        recent_scenes=[h.get('store_scene_id') for h in history]
        # Several photos of one piece of furniture share a label prefix ("Fauteuil cuir · …"): change place, not just angle.
        place=lambda scene:scene['label'].split(' · ')[0].strip().lower()
        labels={s['id']:place(s) for s in scenes}
        last_place=labels.get(recent_scenes[0]) if recent_scenes else None
        scene=min(eligible,key=lambda s:(s['id'] in recent_scenes[:3],place(s)==last_place,recent_scenes.count(s['id']),s['id'] not in matched,s['recent_uses'],s['created']))
    camera=None
    if scene:
        # Never the same viewpoint twice in a row, and rotate viewpoints within each place.
        options=CAMERAS_BY_STAGING.get(staging,['front'])
        recent_cameras=[h.get('camera') for h in history]
        same_place=[h.get('camera') for h in history if h.get('store_scene_id')==scene['id']]
        camera=min(options,key=lambda c:(c==(recent_cameras[0] if recent_cameras else None),same_place.count(c),recent_cameras.count(c),options.index(c)))
    return {'staging':staging,'camera':camera,'store_scene':{k:scene[k] for k in ('id','label','description','tags')} if scene else None}


def next_template(store,has_product,exclude=None):
    """Least recently used designed frame; tip cards only for advice posts."""
    candidates=['classic','minimal','raw']+([] if has_product else ['tip_card'])
    with store.db() as db:
        rows=db.execute("SELECT id,content FROM items WHERE kind='social' AND media!='{}' ORDER BY scheduled_at DESC LIMIT 8").fetchall()
    recent=[json.loads(r['content']).get('template') for r in rows if r['id']!=exclude]
    return min(candidates,key=lambda t:(t in recent[:2],recent.count(t),candidates.index(t)))


def checked_options(value):
    options=value.get('directions') if isinstance(value,dict) else None
    if not isinstance(options,list) or len(options)!=3:raise Conflict('La direction visuelle doit proposer trois mises en situation cohérentes.')
    result=[]
    for option in options:
        if not isinstance(option,dict) or option.get('setting') not in SETTINGS or option.get('lighting') not in LIGHTS or option.get('angle') not in ANGLES:raise Conflict('Direction photographique inexploitable.')
        for key in ('scene','product_fit'):
            if not isinstance(option.get(key),str) or not 15<=len(option[key].strip())<=1400:raise Conflict('Le décor et sa cohérence avec le produit doivent être précisés.')
        result.append({k:option[k].strip() for k in ('setting','lighting','angle','scene','product_fit')})
    if len({(o['setting'],o['lighting'],o['angle']) for o in result})!=3:raise Conflict('Les trois pistes visuelles doivent réellement varier.')
    return result


def select(options,history):
    counts=Counter(h.get('setting') for h in history)
    # Recency matters first: an alternative setting should beat the last used one,
    # even if that last setting is less common across the whole recent series.
    recent={h.get('setting') for h in history[:2]}
    combos=Counter((h.get('setting'),h.get('lighting'),h.get('angle')) for h in history)
    return min(options,key=lambda o:(o['setting'] in recent,counts[o['setting']],combos[(o['setting'],o['lighting'],o['angle'])],o['lighting']==(history[0].get('lighting') if history else None),o['angle']==(history[0].get('angle') if history else None)))


def choose(store,ask,item,brief,product):
    with store.db() as db:
        old=db.execute('SELECT body FROM visual_directions WHERE item_id=? AND revision=?',(item['id'],item['revision'])).fetchone()
        if old:return json.loads(old[0])
        history=[json.loads(r[0]) for r in db.execute('SELECT body FROM visual_directions ORDER BY rowid DESC LIMIT 12')]
        # Include legacy scenes as context so the first deployment does not start
        # from a blank visual memory. They do not claim to describe image pixels.
        legacy=[{'brief_scene':json.loads(r[0]).get('scene','')} for r in db.execute("SELECT content FROM items WHERE id!=? AND media!='{}' AND id NOT IN (SELECT item_id FROM visual_directions) ORDER BY rowid DESC LIMIT 8",(item['id'],))]
    plan=plan_staging(store,item,brief,product,history)
    place=plan['store_scene']
    staging_text='\nMise en scène imposée pour ce post : '+STAGINGS[plan['staging']]+'. Les trois pistes respectent cette mise en scène et varient placement, lumière et cadrage.'
    if plan.get('camera'):
        staging_text+='\nPoint de vue imposé : '+CAMERAS[plan['camera']]+'. Les trois pistes gardent ce point de vue et varient placement et lumière.'
    if place:
        staging_text+='\nLieu réel imposé : notre magasin, photo du lieu jointe à la génération — '+place['label']+(' : '+place['description'] if place['description'] else '')+'. Utilisez setting="store" et décrivez précisément où et comment le produit y est placé (posé sur le canapé, appuyé au mur, sur un stand…) sans inventer de mobilier absent de ce lieu.'
    prompt='Vous préparez la direction photographique, pas le texte du post. '+RULES+staging_text+'\nProposez trois mises en situation adaptées au produit et à l’angle éditorial, dans trois lieux différents lorsque le brief le permet. Si un lieu est explicitement imposé par le propriétaire, conservez-le et variez lumière et cadrage. Une ancienne mention générique de « studio chaleureux » ou de bois n’est pas une contrainte de charte. Évitez les scènes récentes ci-dessous. Pour chaque piste, expliquez son adéquation au produit sans inventer ses caractéristiques. Intérieurs uniquement sauf contexte extérieur explicitement documenté (dans ce cas privilégiez tout de même une proposition intérieure sûre).\nProduit vérifié : '+dumps(product)+'\nSujet : '+dumps({k:item['content'].get(k) for k in ('title','facebook','instagram','excerpt','scene','_visual_feedback')})+'\nBrief : '+dumps(brief)+'\nDirections récentes (la première est la plus récente) : '+dumps(history)+'\nAnciens briefs de décor, pas une analyse de pixels : '+dumps(legacy)+'\nCatégories de lieu : '+dumps({k:v for k,v in SETTINGS.items() if place or k!='store'})+'\nÉclairages autorisés : '+dumps(sorted(LIGHTS))+'\nCadrages autorisés : '+dumps(sorted(ANGLES))+'\nJSON : {"directions":[{"setting":"catégorie autorisée","lighting":"éclairage autorisé","angle":"cadrage autorisé","scene":"description concrète du lieu, placement du produit, matériaux, lumière, cadrage et accessoires de contexte discrets","product_fit":"pourquoi ce cadre et cette installation conviennent à CE produit ou conseil"}]}. Exactement trois pistes différentes. Aucun texte dans l’image.'
    visual_instructions = brief.get('visual_instructions') or item['content'].get('visual_instructions')
    if isinstance(visual_instructions, str) and visual_instructions.strip():
        prompt += ('\nConsignes visuelles explicites de l’agent ou du propriétaire, prioritaires sur '
                   'les suggestions de variété : respectez-les dans chaque piste sans les remplacer '
                   'par une direction générique. Texte fourni : ' + dumps(visual_instructions))
    options=checked_options(ask(prompt))
    for option in options:
        # Only a real photo of the shop may place the scene in the shop.
        if place:option['setting']='store'
        elif option['setting']=='store':option['setting']='architecture'
    chosen=select(options,history)
    direction={**chosen,'staging':plan['staging'],'camera':plan.get('camera'),'store_scene_id':place['id'] if place else None,'store_scene_label':place['label'] if place else None,'version':VERSION,'created_at':now()}
    with store.db() as db:
        current=store.item(item['id'],db)
        if current['revision']!=item['revision'] or current['status'] not in ('queued','generating','rendering','failed','review'):raise Conflict('Le contenu a changé pendant le choix du décor.')
        db.execute('INSERT OR IGNORE INTO visual_directions VALUES(?,?,?)',(item['id'],item['revision'],dumps(direction)))
        return json.loads(db.execute('SELECT body FROM visual_directions WHERE item_id=? AND revision=?',(item['id'],item['revision'])).fetchone()[0])
