"""Choose varied, product-compatible photographic directions before rendering."""
import json
from collections import Counter
from store import Conflict, dumps, now

VERSION='pl-scenes-v2'
SETTINGS={
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
RULES='''La charte commune vient du logo, de la typographie et de l’habillage ajoutés par le logiciel, PAS d’un décor identique. Variez les lieux, matériaux, lumières et cadrages. Aucun studio chaleureux / bois / bokeh / accent vert obligatoire. Le produit reste entier, fidèle et clairement mis en situation, jamais détouré ou isolé sur fond blanc. Choisissez un usage crédible pour ce modèle précis : un piano ne devient pas un appareil DJ, une enceinte de studio ne devient pas une enceinte de festival, un micro de prise de son ne devient pas arbitrairement un micro de scène. Ne suggérez aucune résistance à l’eau, utilisation extérieure, compatibilité, accessoire fourni ou capacité technique non documentée. Ne représentez pas notre magasin, nos clients ou un événement réel sans photo correspondante. Les références déterminent le modèle et ses couleurs, pas leur arrière-plan.'''


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
    prompt='Vous préparez la direction photographique, pas le texte du post. '+RULES+'\nProposez trois mises en situation adaptées au produit et à l’angle éditorial, dans trois lieux différents lorsque le brief le permet. Si un lieu est explicitement imposé par le propriétaire, conservez-le et variez lumière et cadrage. Une ancienne mention générique de « studio chaleureux » ou de bois n’est pas une contrainte de charte. Évitez les scènes récentes ci-dessous. Pour chaque piste, expliquez son adéquation au produit sans inventer ses caractéristiques. Intérieurs uniquement sauf contexte extérieur explicitement documenté (dans ce cas privilégiez tout de même une proposition intérieure sûre).\nProduit vérifié : '+dumps(product)+'\nSujet : '+dumps({k:item['content'].get(k) for k in ('title','facebook','instagram','excerpt','scene','_visual_feedback')})+'\nBrief : '+dumps(brief)+'\nDirections récentes (la première est la plus récente) : '+dumps(history)+'\nAnciens briefs de décor, pas une analyse de pixels : '+dumps(legacy)+'\nCatégories de lieu : '+dumps(SETTINGS)+'\nÉclairages autorisés : '+dumps(sorted(LIGHTS))+'\nCadrages autorisés : '+dumps(sorted(ANGLES))+'\nJSON : {"directions":[{"setting":"catégorie autorisée","lighting":"éclairage autorisé","angle":"cadrage autorisé","scene":"description concrète du lieu, placement du produit, matériaux, lumière, cadrage et accessoires de contexte discrets","product_fit":"pourquoi ce cadre et cette installation conviennent à CE produit ou conseil"}]}. Exactement trois pistes différentes. Aucun texte dans l’image.'
    chosen=select(checked_options(ask(prompt)),history)
    direction={**chosen,'version':VERSION,'created_at':now()}
    with store.db() as db:
        current=store.item(item['id'],db)
        if current['revision']!=item['revision'] or current['status'] not in ('queued','generating','rendering','failed','review'):raise Conflict('Le contenu a changé pendant le choix du décor.')
        db.execute('INSERT OR IGNORE INTO visual_directions VALUES(?,?,?)',(item['id'],item['revision'],dumps(direction)))
        return json.loads(db.execute('SELECT body FROM visual_directions WHERE item_id=? AND revision=?',(item['id'],item['revision'])).fetchone()[0])
