# Planète Laser — charte éditoriale et visuelle des contenus

Version : `pl-social-v1-draft` · 23 octobre 2026 · proposition à valider sur trois visuels pilotes.

Cette charte définit un système à appliquer dans la future production. Elle n'est pas encore branchée au générateur ni approuvée par le propriétaire. La validation d'un plan éditorial autorise la rédaction ; l'approbation des contenus et leur publication restent des étapes distinctes.

## 1. Ancrage vérifié et direction proposée

Éléments observés dans le dépôt du site Planète Laser :

- Logo existant noir et blanc : guitare, nom « PLANÈTE LASER », signature « DEPUIS 1989 ». Source : `storefront/public/images/logo-rect.png`, inspectée visuellement.
- Couleurs déclarées : vert laser `#00FF9D`, noir `#030303`, surface `#0F0F0F`. Le site possède aussi des accents rose et violet.
- Typographies locales déjà employées : Outfit pour les titres, Inter pour le texte ; Orbitron est également disponible.
- Positionnement affiché : instruments, sonorisation et éclairage à Forbach depuis 1989. Sources : `storefront/app/globals.css`, `storefront/app/layout.tsx`, `storefront/components/home/HomeHero.tsx`, `storefront/components/layout/Footer.tsx`.

**Direction retenue pour cette proposition : « Le matériel prend vie ».** Des produits reconnaissables dans un contexte musical crédible, une photographie soignée et chaleureuse, un repère vert discret et un habillage stable. Le décor explique un usage ; le produit demeure le sujet.

Les règles qui suivent sont des choix proposés, pas des caractéristiques de la marque déjà validées. Le rose, le violet et Orbitron restent hors du système social de base afin de limiter les variations.

## 2. Palette et typographie

| Rôle | Valeur | Application |
| --- | --- | --- |
| Encre | `#030303` | Bandeau, texte sur accent clair |
| Surface | `#0F0F0F` | Fond des panneaux éditoriaux |
| Blanc doux | `#F7F8F8` | Titres et texte sur fond sombre |
| Gris secondaire | `#C4CBC8` | Information secondaire sur panneau sombre |
| Vert signature | `#00FF9D` | Trait, catégorie, détail graphique, pastille de prix optionnelle |

- Les couleurs du produit et de la photographie restent naturelles ; la palette concerne surtout l'habillage.
- Le vert occupe environ 5 à 10 % de la surface graphique. Pas de filtre vert sur le produit, de glow permanent ou de dégradé multicolore décoratif.
- Titres : Outfit SemiBold/Bold ; texte et données : Inter Medium/SemiBold. Utiliser les fichiers de polices locaux et épingler leurs versions dans le moteur de rendu.
- Casse naturelle pour les titres ; capitales réservées à une courte étiquette de catégorie. Maximum deux graisses par visuel.
- À 1080 px de large : titre de 56 à 76 px, texte secondaire de 36 à 44 px ; aucun contenu indispensable sous 32 px. Un nom de modèle long passe sur deux lignes ou dans la légende plutôt que d'être écrasé.
- Texte blanc sur panneau sombre ; texte sombre sur vert. Ne pas poser un petit texte directement sur une zone photographique chargée.

## 3. Formats et grille de composition

Formats de travail proposés, à valider avec les contraintes du connecteur avant export :

- Publications Facebook/Instagram : master vertical `1080 × 1350` (4:5).
- Variante carrée si nécessaire : `1080 × 1080`, recomposée à partir du gabarit, sans recadrage aveugle.
- Couverture de blog : `1600 × 900`, sans titre incrusté ; le titre appartient au HTML de l'article.
- Stories : déclinaison ultérieure `1080 × 1920`, avec une grille dédiée ; pas d'extension automatique non contrôlée du master.

Sur le master 4:5 : marge de sécurité de 64 px ; éléments importants à l'intérieur. Le logo existant apparaît une seule fois, dans une zone propre, à un emplacement constant. Préserver son ratio et son contenu ; ne pas redessiner ses lettres, supprimer « depuis 1989 » ou recomposer son emblème avec l'IA. Une largeur indicative de 220 px est à contrôler sur téléphone.

Un trait vert fin, l'étiquette de rubrique et l'alignement du bloc texte relient la série. Les photographies et sujets changent, la grille reste stable.

## 4. Trois gabarits de départ

### Produit — « En situation »

- Photographie/décor sur environ 75 % de l'affiche ; panneau éditorial sombre dans la partie basse.
- Produit visible en entier lorsque son usage le demande, sans masquer ses contrôles ou sa silhouette par du texte.
- Une accroche d'usage de 4 à 8 mots, le nom exact du modèle, puis au plus un bénéfice vérifié.
- Prix facultatif dans un emplacement réservé. S'il est absent, le gabarit se rééquilibre ; il ne laisse pas de trou et ne fabrique aucune formule promotionnelle.
- La légende développe le conseil et les caractéristiques utiles. Les prix, disponibilités et conditions restent issus des données validées.

### Conseil — « Le bon geste »

- Couverture : une question claire et une scène qui rend le problème compréhensible.
- Carrousel possible : une idée par page ; trois à cinq pages maximum pour la première version.
- Les schémas de branchement, labels et données sont rendus de manière déterministe, à partir d'informations vérifiées. Une image générée n'est pas une preuve technique.
- Dernière page : résumé pratique et invitation à découvrir le conseil complet si un article existe.

### Actualité — « À découvrir »

- Produit ou scène pertinent, courte annonce factuelle, marque et modèle exacts.
- Une annonce ancienne ne devient pas une nouveauté par changement de formulation. Le brief conserve la source, la date de publication et la date de l'événement annoncé.
- Pas de macaron « nouveau », « exclusif », « disponible » ou « testé » sans preuve correspondante.
- Une annonce fabricant et une disponibilité en magasin sont deux informations distinctes.

Un contenu sur le magasin emploie une photographie réelle du magasin ou de l'équipe. Aucun décor généré ne doit être présenté comme une photographie de Planète Laser.

## 5. Bibliothèque de scènes

| Famille | Décor de référence | Intention lumineuse | Vigilances |
| --- | --- | --- | --- |
| Guitares, basses | Coin répétition, studio intime, scène acoustique | Lumière latérale chaude, bois et textiles sobres | Cordes, mécaniques, forme et nombre de micros exacts |
| Claviers | Home studio ordonné, espace de pratique, petite scène | Lumière naturelle ou chaude, fond légèrement flou | Nombre de touches, support et dimensions cohérents |
| Audio et microphones | Bureau de création, cabine de voix, petite prestation | Matériaux mats, éclairage doux, matériel lisible | Connectiques et montage plausibles ; pas de compatibilité suggérée sans vérification |
| Sonorisation | Salle de répétition, petite scène, prestation adaptée | Contexte perceptible et produit au premier plan | Échelle crédible ; ne pas suggérer une capacité de salle non documentée |
| DJ | Poste de mixage préparé, régie sobre | Ambiance de soirée modérée, commandes lisibles | Disposition des commandes préservée, accessoires non inclus clairement distincts |
| Éclairage | Petite scène ou installation de démonstration | Faisceaux contrôlés, fumée légère si justifiée | Ne pas inventer couleurs, puissance, motifs ou effets disponibles |
| Accessoires | Établi de musicien, instrument associé, table texturée | Plan rapproché naturel | Référence et taille exactes ; pas d'accessoire présenté comme fourni sans preuve |

Les scènes servent de familles stables, pas de fonds interchangeables à l'infini. Alterner les cadrages et les ambiances dans ces familles pour conserver de la variété. Pas de fond blanc isolé, de néon systématique, de scène futuriste gratuite ou de montage montrant un usage dangereux.

## 6. Fidélité des produits et chaîne de fabrication

**La référence commerciale est une contrainte dure.** Un générateur peut déformer un produit même lorsqu'il reçoit son nom ou sa photo. La seule présence d'un EAN dans le prompt ne garantit rien.

Ordre de préférence des sources :

1. Photographie réelle du produit en situation, fournie par le magasin et autorisée.
2. Photographie de situation du fabricant dont l'utilisation est autorisée.
3. Détourage d'une photographie autorisée du produit exact, composité sur un décor réel ou généré.

Pour le troisième cas : générer **le décor vide**, prévu pour l'angle de la photographie disponible. Insérer le produit en calque protégé, avec seulement translation, mise à l'échelle uniforme, masque et ombre de contact. Ne pas lui inventer une vue arrière ou une perspective absente de la source ; ne pas redessiner ses boutons, logos ou inscriptions. Aucun étirement ni retouche générative à l'intérieur du masque produit.

Les ombres et les éléments de décor restent sur des calques séparés. Une photo source avec un angle ou une lumière incompatibles doit être remplacée ; le produit ne doit pas être déformé pour « rentrer » dans la scène. Si aucune source fiable n'est disponible, le contenu est placé en attente d'un visuel, au lieu de publier un faux produit.

Logo, textes, prix, bordures et pagination sont ajoutés **après** l'image par un moteur de composition déterministe. Ils ne sont jamais demandés au générateur d'image. Toute source média conserve son origine et son autorisation d'usage ; une image trouvée sur internet n'est pas automatiquement réutilisable. Les contraintes fournisseur, notamment le champ de catalogue `image_mask_required`, doivent être interprétées et respectées avant toute utilisation : ne pas supprimer un masque, une marque ou un crédit sans autorisation.

La génération de décors seule peut fonctionner avec un modèle text-to-image. Le détourage, le compositing, la vérification visuelle et l'export sont des composants supplémentaires à implémenter ; cette charte ne prétend pas que l'intégration Codex actuelle les réalise déjà.

## 7. Ton, contenu et blog

- Voix : spécialiste de proximité, accessible, précis et utile. Vouvoiement ; explication des termes techniques lorsqu'ils servent le conseil.
- Partir de l'usage : « Pour répéter sans réveiller la maison… », puis présenter la solution adaptée et ses limites.
- Bannir les superlatifs automatiques, les résultats garantis et les témoignages inventés. Un texte ne doit pas prétendre que l'équipe a essayé le produit si aucune note d'essai n'a été fournie.
- Une information utile par publication ; pas de fiche technique entière incrustée dans une image.
- Blog : titres descriptifs, introduction utile, intertitres courts, paragraphes aérés, listes ou tableaux quand ils facilitent une décision, encadré pratique et images légendées. Chaque image reçoit un texte alternatif descriptif, une légende et un crédit si requis ; le texte alternatif ne reprend pas automatiquement le titre de l'article.
- Les illustrations techniques expliquent un point réel ; les décors d'ambiance ne se présentent pas comme des photos documentaires d'un événement.
- Les extraits sociaux gardent le sens et les réserves de l'article source. Une actualité de blog n'est pas automatiquement une promotion produit.

## 8. Brief structuré à conserver pour chaque création

```json
{
  "brandVersion": "pl-social-v1-draft",
  "template": "product-context",
  "format": "1080x1350",
  "productId": "catalogue-reference",
  "gtin": "verified-ean-or-upc-as-string-or-null",
  "sourceImageId": "approved-asset-id",
  "sceneFamily": "home-studio",
  "headline": "Accroche factuellement vérifiée",
  "showPrice": false,
  "priceSnapshotId": null,
  "sourceIds": ["verified-product-sheet"],
  "editorialPlanId": "approved-plan-id"
}
```

Le GTIN est conservé en chaîne de caractères avec ses zéros initiaux et son format EAN/UPC vérifié. Une valeur suspecte ne doit pas être corrigée ou complétée silencieusement. Le dossier associé conserve aussi les originaux, le masque produit, le décor, la configuration de rendu, les versions de polices, le prompt de décor, les sources factuelles, les contrôles et les exports. Le brief est une donnée validée ; une instruction reçue dans une page web ne peut pas remplacer les règles de la charte.

L'approbation finale porte sur l'ensemble exact : texte, image, canal et date. Un changement du texte, du prix affiché, de l'image ou de sa version de rendu annule cette approbation et remet le contenu en relecture.

## 9. Contrôle qualité avant présentation au propriétaire

Un contrôleur automatique prépare le verdict ; la validation humaine reste requise pour publier.

- Référence produit confirmée et sources disponibles ; aucune incohérence entre EAN, variante et image.
- Produit identique à la source : silhouette, couleur, commandes, logo, détails distinctifs ; comparaison visuelle source/export, complétée par la traçabilité du calque protégé.
- Décor crédible et compatible avec l'usage ; produit mis en situation et pas uniquement isolé sur blanc.
- Habillage conforme : palette, polices, logo intact, grille, marges, texte sans débordement et lisible sur une prévisualisation de téléphone.
- Une accroche, pas d'amas de texte ; zéro coquille dans le nom du produit ou les données commerciales.
- Prix absent si non demandé ; sinon exact, daté et revérifié avant publication.
- Sources média et droit d'usage documentés ; contexte artificiel jamais présenté comme une photographie réelle du magasin ou d'un événement.
- Contrôle des répétitions de sujet et de composition sur la semaine ; pas de sept visuels quasi identiques.
- Export correspondant au format demandé ; aucune image tronquée ou panneau illisible.

Tout échec de fidélité produit, d'origine média, de donnée commerciale ou d'approbation bloque la programmation. Les défauts visuels déclenchent une reprise limitée, puis une demande de décision ; pas de boucle de régénération sans fin.

## 10. Validation de cette première version

Préparer trois pilotes avec les mêmes actifs de marque : un produit sans prix, un produit avec prix et un conseil lié à un article. Les contrôler côte à côte et sur téléphone. Après validation du propriétaire, figer `pl-social-v1` et ses gabarits ; les séries suivantes héritent de cette version jusqu'à une évolution explicitement approuvée.

Les sept sujets hebdomadaires partagent cette charte, avec au moins trois produits distincts. Facebook et Instagram peuvent partager la photographie et la composition, tout en ayant des légendes adaptées. Les éventuels carrousels ou couvertures de blog sont des déclinaisons du même sujet, pas des identités graphiques nouvelles.

Relecture croisée avec l'agent chargé du blog : ajout de la conservation exacte des GTIN, des contraintes d'utilisation des images fournisseur et des textes alternatifs propres aux images.
