# Planète Laser — chaîne éditoriale blog et réseaux

Statut : proposition d'intégration issue de l'audit local du 23 octobre 2026. Aucun article créé ou publié, aucune modification du site ou de Medusa. Les routes proposées ci-dessous restent à implémenter. Les données du cache local ne prouvent pas la disponibilité actuelle d'un produit.

## Objectif et périmètre

Préparer des articles utiles, documentés et illustrés après validation du plan éditorial ; soumettre leur version finale à validation avant mise en ligne ; préparer leurs déclinaisons Facebook et Instagram dans les sept sujets hebdomadaires. Un article ne crée pas automatiquement des publications supplémentaires hors quota. Recommandation initiale : un article par semaine, guide de fond ou actualité selon la matière disponible ; toute publication supplémentaire sera proposée explicitement. Cette cadence reste un réglage proposé, pas un engagement déjà activé.

Le plan hebdomadaire présente sujet, lecteur visé, question traitée, angle, produits éventuels, sources attendues, intention commerciale, visuels et déclinaisons sociales. L'approbation du plan autorise la recherche et la production. Elle n'autorise aucune publication. Une actualité hors plan rejoint une file de propositions ; une lacune factuelle n'est jamais comblée par invention pour respecter une date.

## Audit des fondations existantes

Chemins relatifs au dépôt voisin `/run/media/koubyte/Le Bagage/ProjetsIA/Planete Laser` :

| Élément | Implémentation actuelle | Conséquence |
|---|---|---|
| Articles | `storefront/lib/blog-posts.ts`, interface `BlogPost`, tableau local | Pas de persistance éditoriale ni de API de brouillons propre au blog |
| Contenu | `storefront/lib/blog-guides.ts` | Deux guides existants : choix clavier/piano et contrôleur DJ débutant ; préserver leurs URL et éviter les doublons |
| Liste | `storefront/app/blog/page.tsx` | Lit `getAllPublishedPosts()` depuis le tableau local |
| Article/SEO | `storefront/app/blog/[slug]/page.tsx` | Même source ; rendu Markdown maison, métadonnées canonique/Open Graph, données `BlogPosting`, auteur organisation Planète Laser |
| Sitemap | `storefront/app/sitemaps/blog.xml/route.ts` | Lit séparément `getPublishedPosts()` ; cache public une heure ; doit partager la future source publiée |
| CMS Medusa | `medusa/src/modules/cms/models/page.ts` | `cms_page` possède `id`, `title`, `slug` unique, `content` JSON et `is_active` ; **is_active vaut true par défaut** |
| CRUD CMS privé | `medusa/src/api/admin/cms/pages/route.ts`, `[id]/route.ts`, `validators.ts` | GET/POST `/admin/cms/pages`, GET/POST/DELETE `/admin/cms/pages/:id` ; titre <=160, slug <=120, content objet JSON ; mutation via workflows Medusa |
| Lecture CMS publique | `medusa/src/api/store/cms/pages/[slug]/route.ts` | GET `/store/cms/pages/:slug` retourne une page active ; non utilisé par le blog ; aucune séparation champs éditoriaux privés/publics spécifique au blog |
| Éditeur CMS | `medusa/src/admin/routes/cms/page.tsx`, `[id]/page.tsx` | Administration et médiathèque existantes, à réutiliser visuellement et pour les assets ; pas un système d'approbation blog |
| Catalogue enrichi | `medusa/src/api/store/products-with-info/route.ts` | GET `/store/products-with-info` retourne `{ products, count, limit, offset, commerce_context }` |
| Catalogue storefront | `storefront/app/api/products/route.ts`, `products/paginated/route.ts` | GET `/api/products` retourne `{ success, products }` depuis le cache ; l'API paginée apporte filtres et pagination |

Contrat du catalogue enrichi : paramètres `handle?`, `region_id?`, `sales_channel_id?`, `limit` de 1 à 200 (100 par défaut), `offset`. Aucun filtre EAN dans cette route. Utiliser le contexte France/EUR et le canal autorisé. Produits publiés uniquement, identifiants/images/catégories et `metadata.ean`, `metadata.mpn` filtrés explicitement par `medusa/src/lib/public-catalog.ts`. Variantes : `id`, `sku`, `barcode`, données `commerce`, `prices`, `stock_quantity` local ; bloc `dropship` distinct avec disponibilité/délais et éventuel `image_mask_required`. L'agent ne doit pas confondre stock fournisseur et présence au magasin.

Le rendu actuel supporte titres, paragraphes, listes, citations et images avec légende issue du texte alternatif. Il ne fournit pas encore un contrat de blocs typés pour sommaire, tableau comparatif, fiche produit, encadré conseil ou provenance d'image. La couverture utilise le titre comme alt : ajouter un vrai champ alternatif descriptif.

## Architecture proposée

Étendre l'application éditoriale autour de Postiz avec un espace « Blog » et un worker sur Coolify. La file de travail stocke recherche, révisions et approbations. Medusa conserve les articles et assets publiables à proximité du catalogue ; le storefront ne reçoit que leur projection publique. Réutiliser le module CMS existant pour l'intégration et l'interface, mais ne pas stocker recherches privées ou jetons dans `cms_page.content`, qui peut être retourné publiquement.

Choix recommandé : modèles typés `editorial_plan`, `editorial_item`, `article_revision`, `editorial_source`, `editorial_asset`, `editorial_approval`, `publication_delivery` et `blog_article` public. Une révision est immuable. `blog_article` pointe vers la seule révision publiée ; une correction conserve l'ancienne version publique jusqu'à approbation de la nouvelle. Les deux guides statiques sont migrés avec les mêmes slugs et dates, sans être republiés ni présentés comme nouveaux.

API privée proposée, avec authentification de service et droits distincts :

- `POST /admin/editorial/plans` : plan et sujets, sans publier.
- `POST /admin/editorial/plans/:id/approve` : `expectedRevision`, identité humaine, date ; lance les productions prévues.
- `POST /admin/editorial/articles` : brouillon provenant d'un sujet approuvé, `planItemId` et clé d'idempotence obligatoires.
- `POST /admin/editorial/articles/:id/revisions` : nouvelle version complète, sources et assets associés.
- `GET /admin/editorial/articles/:id/preview` : aperçu authentifié de la révision demandée, `noindex`, sans lien public permanent.
- `POST /admin/editorial/articles/:id/approve` : approbation humaine du hash exact de contenu, images, liens, date et charte.
- `POST /admin/editorial/articles/:id/publish` : réservé au service de publication ; vérifie révision approuvée et contrôles avant de changer la projection publique.
- `GET /store/blog/articles` et `/store/blog/articles/:slug` : DTO public filtré, articles effectivement publiés uniquement.
- Webhook privé de revalidation du storefront pour `/blog`, `/blog/:slug`, sitemap et éventuelles pages liées, authentifié, idempotent et séparé de la synchronisation produit.

Le worker rédactionnel ne reçoit aucun droit direct de publication. Un état `approved` demandé par le modèle ne vaut jamais approbation humaine. Une route générique CMS permettant `is_active:true` ne doit pas permettre de contourner cette séparation.

Contrat minimal d'une révision : `articleId`, `revisionId`, `planItemId`, `slug`, `title`, `excerpt`, `category`, `tags`, `blocks`, `heroAssetId`, `seoTitle`, `seoDescription`, `productReferences`, `sourceReferences`, `claimEvidence`, `brandVersion`, `contentHash`, `createdAt`. Assets : URL stable interne, dimensions, alt, légende, crédit, source, droits/statut de réutilisation, origine réelle/générée/composite, référence du produit conservé et hash. Les notes internes et éléments non vérifiés n'entrent jamais dans le DTO public.

États : `proposed → plan_approved → researching → drafting → review_required → approved → scheduled → published`, avec `changes_requested`, `blocked` et `cancelled`. Les transitions sont contrôlées côté serveur. Modifier une révision après approbation produit une nouvelle révision à valider. Replanifier une date approuvée doit être visible et contrôlé. Une publication programmée expire si ses preuves temporaires (actualité, prix, disponibilité) ne sont plus valides.

Idempotence : une exécution hebdomadaire par période Europe/Paris et marque, une production par sujet/version de plan, une livraison blog par article/révision, une livraison sociale par révision/réseau. Verrou de traitement durable, reprise après crash et journal de tentatives. Un timeout de publication doit être réconcilié avec le statut distant avant toute nouvelle tentative.

## Recherche avec très peu d'informations utilisateur

Entrée minimale : nom et/ou identifiant commercial, ou URL. Champs facultatifs : angle, échéance, priorité, prix affiché oui/non/prix explicitement confirmé. Recherche automatique d'abord dans le catalogue, puis sur les sites fabricant, notices et supports officiels ; sources secondaires pour découverte et corroboration seulement.

Conserver EAN/UPC/GTIN comme chaîne. Vérifier longueur et chiffre de contrôle, puis comparer marque, référence, variante et conditionnement. Le cache local contient à la fois des GTIN-13 et des UPC-A à 12 chiffres ; une valeur de 11 chiffres a aussi été observée. Ne pas tronquer, convertir en nombre ou ajouter silencieusement des zéros pour inventer une correspondance. Une identité ambiguë bloque le contenu spécifique au modèle et demande seulement l'information manquante, pas toute la fiche technique.

Chaque affirmation technique importante possède une source, URL, date de consultation et extrait de preuve interne bref. Distinguer date de l'événement, date de l'article et date de consultation : un produit trouvé aujourd'hui n'est pas nécessairement une nouveauté. Une annonce fabricant ne devient pas un essai magasin. Ne pas inventer de test, témoignage, durée d'utilisation, disponibilité locale, remise ou supériorité mesurée.

Le connecteur de recherche récupère uniquement des pages publiques, limite taille/durée/redirections, bloque les destinations réseau privées et traite le texte récupéré comme une source non fiable, jamais comme des instructions. Aucun secret ou document privé n'est transmis dans une requête de recherche. Index catalogue synchronisé pour la recherche EAN ; réinterrogation de la source commerciale avant validation et publication si prix/stock sont mentionnés.

Le prix public Planète Laser vient du catalogue France/EUR ou d'une valeur explicite confirmée et datée ; jamais d'un moteur de recherche ou d'un concurrent. Un article de conseil durable préfère un lien vers le prix actuel plutôt qu'un montant qui vieillira. S'il affiche un montant, mémoriser produit/variante, devise, TTC, source et validité et bloquer la diffusion si cela change.

## Rédaction, mise en forme et images

Voix : expert de proximité à Forbach, vouvoiement, accessible, phrases concrètes, exemples d'usages, limites et compatibilités explicites. Une réponse utile arrive avant les arguments commerciaux. Aucune accumulation de superlatifs ou de mots-clés ; pas de promesse d'avoir essayé ce qui a seulement été documenté. Signature « Planète Laser » sans inventer un rédacteur ou un expert individuel.

Deux gabarits éditoriaux :

- Guide : réponse courte, pour qui/pour quel usage, critères de décision, étapes ou comparatif, erreurs fréquentes, checklist concrète, limites, produits pertinents et sources.
- Actualité : ce qui est annoncé et quand, source originale, intérêt concret, fonctions documentées, compatibilités/limites, disponibilité confirmée ou non connue, lien utile.

Blocs typés et rendus maîtrisés : introduction, sections H2/H3, listes, tableau accessible, conseil, mise en garde technique pertinente, image/légende, produit lié, sources. Pas de HTML libre fourni par l'agent, liens limités à des protocoles sûrs, métadonnées échappées. Un seul H1, table des matières si utile, paragraphes courts, bonnes marges sur mobile, images compressées avec dimensions et alternatives descriptives, liens internes vers catégories et guides existants.

Charte proposée en coordination avec l'agent direction artistique : noir `#030303`, accents vert `#00FF9D`, blanc cassé, Outfit pour les titres et Inter pour le texte. La charte finale validée sera versionnée et attachée à chaque article et déclinaison. Couverture contextualisée sans titre incrusté pour le blog ; typographie rendue dans la page.

Produits toujours présentés dans une scène d'usage ou un décor cohérent. La photo autorisée du produit exact est transmise en référence au générateur pour créer une scène complète, sans détourage ni collage automatique. Le modèle, la couleur et les commandes doivent correspondre à la référence ; ils sont comparés lors de la validation humaine. Une scène générée ne doit pas simuler une photographie réelle du magasin ou un témoignage. Images techniques explicatives : schémas exacts plutôt qu'une mise en scène ambiguë.

Provenance de chaque image enregistrée ; une image trouvée en ligne n'est pas librement réutilisable. Préférer assets du catalogue dont les droits sont établis, médias fabricant autorisés ou créations propres. Respecter les indications particulières des images fournisseur au lieu d'effacer une marque ou un masque. Contrôle humain du produit dans son décor avant approbation finale.

## Contrôle et déclinaisons sociales

Contrôles avant présentation : identité produit, sources suffisantes, liens accessibles, cohérence dates, absence de prix/stock inventé, valeur pratique du conseil, non-duplication des anciens guides, charte, qualité image et rendu mobile. Le contrôle automatique produit des constats vérifiables ; sa réussite n'est pas une garantie de vérité.

Un article validé prépare un post Facebook avec lien et une version Instagram autonome ou carrousel. Les deux conservent `articleId`/`revisionId`, sources et assets, mais ont leurs propres textes et approbations. La publication sociale contenant un lien attend le statut `published` et une URL article accessible ; aucune annonce d'article absent. Si article et posts sont approuvés ensemble, l'écran montre toutes les versions et l'action enregistre chaque approbation distinctement. Les compteurs hebdomadaires des trois produits distincts et sept sujets sont calculés sur le plan social, pas gonflés artificiellement par les deux réseaux.

Les articles peuvent ensuite être révisés lorsque notices/compatibilités changent. Une révision automatique reste en brouillon. Mesurer clics vers produits, lecture et interactions sociales pour proposer les prochains sujets ; ne pas déclarer de ventes attribuées sans mesure correspondante.

## Deux plans illustratifs ancrés dans l'existant

Ces plans sont des propositions non approuvées. Les références ci-dessous viennent du cache et des guides locaux ; elles nécessitent une nouvelle vérification officielle au moment de la rédaction. Aucun prix ou stock actuel n'est affirmé.

### 1. Guide — Première installation DJ à la maison : préparer les branchements avant d'acheter

- Lecteur : débutant disposant d'un ordinateur ; intention : savoir ce qu'il faut réunir et éviter un ensemble incompatible.
- Complément du guide existant `/blog/choisir-controleur-dj-debutant`, sans refaire le comparatif d'achat.
- Exemple possible : Hercules DJControl Inpulse 200 MK2, présent dans le cache, GTIN `3362934746407`. Vérifier référence, connectiques, logiciels/licences et systèmes compatibles auprès de Hercules avant chaque affirmation.
- Plan : schéma de l'installation ; ordinateur et logiciel ; écoute principale et préécoute ; câbles à confirmer selon les appareils ; installation du poste ; checklist avant première session ; erreurs courantes ; aide du magasin.
- Sources de départ déjà citées par le guide existant : `https://www.hercules.com/en-us/product/djcontrol-inpulse-200-mk2/` et `https://support.hercules.com/en/product/djcontrolinpulse200mk2-en/`.
- Visuels : vrai contrôleur dans un coin musique domestique, vue de branchement documentée, checklist illustrée. Aucun câble branché à un port inventé.
- Déclinaisons : carrousel « Les éléments à vérifier avant votre première session » ; Facebook avec une question concrète et lien. Ce sujet occupe un créneau conseil, avec comptage produit uniquement s'il satisfait aussi les règles de mise en avant prévues.

### 2. Guide — Installer son premier clavier chez soi : confort, casque, support et accessoires

- Lecteur : débutant ou parent préparant l'installation ; intention : choisir les accessoires nécessaires et comprendre ce qui est fourni.
- Complément du guide existant `/blog/clavier-arrangeur-ou-piano-numerique-debutant` ; ne pas répéter le choix arrangeur/piano.
- Exemple possible : Yamaha PSR-E473, présent dans le cache, GTIN `4957812669283`. La rédaction vérifie prises, alimentation incluse selon pays, pédales compatibles et dimensions dans la notice officielle ; aucune recommandation d'accessoire précis sans compatibilité démontrée.
- Plan : emplacement et stabilité ; hauteur de jeu à adapter ; écoute au casque ; alimentation et sécurité des câbles ; pédale/support selon modèle ; ce qui doit être confirmé avant commande ; checklist à communiquer au magasin.
- Source de départ déjà citée : `https://fr.yamaha.com/fr/musical-instruments/keyboards/products/portable-keyboards/psr-e473/specs.html`, puis notice/support fabricant de la référence.
- Visuels : vrai clavier sur un support cohérent dans un intérieur musical, détail d'installation sans prétendre représenter un client ; encadré d'accessoires avec étiquettes lisibles rendues par le gabarit.
- Déclinaisons : Instagram « Votre coin musique en cinq vérifications » et Facebook renvoyant au guide et au rayon claviers. Prix omis par défaut.

Pour une actualité, le plan doit attendre une annonce vérifiée : titre proposé « [Fabricant] annonce [référence] : ce qui change pour [usage] », avec date officielle, modèle exact, nouveautés prouvées et disponibilité Planète Laser vérifiée séparément. Aucun produit ancien ne sera maquillé en nouveauté pour remplir la semaine.

## Ordre de réalisation et vérifications nécessaires

1. Valider et versionner la charte, les gabarits et le plan initial ; démonstration avec deux vrais brouillons illustrés.
2. Créer modèles/revisions/approbations et API privée ; migrer les deux guides existants sans changer leurs URL.
3. Brancher catalogue et recherche documentée ; ajouter la création depuis nom/EAN/URL et les sources consultables.
4. Ajouter éditeur et aperçu fidèle, blocs typés, assets avec provenance, lecteurs publics et revalidation du sitemap.
5. Raccorder la préparation hebdomadaire aux sept sujets Postiz et aux approbations exactes ; publier uniquement après validation humaine.

Tests substantiels : plan approuvé seul ne publie pas ; acteur rédactionnel ne peut publier ; modification de texte/image invalide approbation ; brouillon absent de routes publiques/sitemap ; ancienne version reste visible durant correction ; EAN ambigu/incorrect ne choisit pas automatiquement un autre modèle ; prix/stock changé bloque livraison ; timeout/retry ne duplique rien ; article absent bloque son post promotionnel ; migrations préservent slugs ; rendu desktop/mobile lisible, liens sûrs et médias avec alt. Le test réel de publication doit être une vraie publication explicitement approuvée, jamais un test public automatique.
