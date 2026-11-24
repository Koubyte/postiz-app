# Planète Laser — système éditorial proposé

Direction, cadence et validations approuvées par le propriétaire le 23 octobre 2026. Le studio implémente la préparation des plans, la rédaction après approbation du plan, les visuels composés, les approbations exactes et les livraisons. Voir services/editorial/README.md pour le fonctionnement livré et ses limites. Les plans hebdomadaires et leurs contenus restent à valider individuellement.

## Résultat attendu

Sept sujets chaque semaine, déclinés chacun pour Facebook et Instagram (14 publications), dont au moins trois produits distincts. Les demandes ponctuelles du magasin remplacent des créneaux du plan ; elles ne créent pas automatiquement une publication supplémentaire. Cadence blog proposée : un article approfondi par semaine au démarrage, actualité ou conseil selon la matière disponible. Ce rythme a été validé.

## Deux validations distinctes

1. Le plan présente les sujets, produits, angles, sources envisagées, visuels prévus, canaux et dates. Sa validation autorise la rédaction des articles et la production des médias.
2. Les contenus terminés sont relus dans un espace commun. L'approbation porte sur une version précise du texte, des médias, des liens, du prix éventuel, des comptes et de la date. Seule cette version peut être publiée.

Changer l'un de ces éléments invalide son approbation. Un plan approuvé ne vaut jamais approbation des futurs textes ou images. Une modification du prix ou de la disponibilité avant publication bloque le contenu concerné et demande une nouvelle revue. À l'heure prévue, un contenu non approuvé reste en attente ; aucun rattrapage silencieux n'est effectué.

## Informations demandées au magasin

Une référence catalogue, un nom avec EAN/UPC, un lien ou une photo et une courte consigne peuvent initier une demande. Champs facultatifs : date limite, priorité, angle, prix visible ou masqué, prix spécifique et durée de validité. Les identifiants sont conservés comme chaînes avec leurs zéros initiaux.

L'agent recherche d'abord dans le catalogue, puis sur les sites du fabricant et les documentations officielles. Il ne réclame des informations supplémentaires que si plusieurs modèles restent possibles ou si une information essentielle demeure introuvable. Une correspondance partielle produit/modèle/code n'est jamais considérée comme certaine.

Les prix et disponibilités Planète Laser viennent du catalogue ou d'une consigne explicitement confirmée. Un prix concurrent trouvé sur Internet n'est pas un prix du magasin. Les stocks magasin, fournisseurs et délais sont distincts.

## Équipe et responsabilités

- Recherche : identifier les références, collecter les sources, dates et faits vérifiables ; conserver les incertitudes.
- Planification : équilibrer produits, conseils, actualités et vie du magasin ; consulter l'historique et les demandes prioritaires.
- Rédaction : produire un article utile puis ses adaptations sociales ; conserver les sources dans le dossier de revue.
- Direction artistique : appliquer la charte approuvée et choisir une scène cohérente avec l'usage du produit.
- Contrôle : vérifier faits, prix, références, lisibilité, fidélité visuelle, droits d'utilisation des médias et absence de répétition avant soumission.

Ces rôles peuvent être des étapes spécialisées d'un même service. La présence de plusieurs agents ne constitue pas une validation : les règles de publication sont appliquées dans le code et la base de données.

## Production visuelle

Voir charte-visuelle.md et sa planche HTML. Pour les produits, le générateur reçoit une photographie autorisée du modèle exact en référence et crée une scène complète, avec perspective, lumière et ombres cohérentes. Aucun détourage/collage de packshot. Logo, typographie, prix et éléments de mise en page sont ajoutés par des gabarits déterministes versionnés.

La photo de référence et le résultat sont comparés avant approbation. L'IA doit conserver couleur, modèle, proportions et commandes ; cette fidélité n'est pas garantie automatiquement. Une référence non identifiée ou une photo soumise à restriction bloque le visuel.

## Blog et réseaux

Voir blog-workflow.md pour l'intégration au site existant. Un même dossier source peut produire un guide de blog et un post qui en extrait un conseil ; pas de copie mécanique du même texte. Une publication sociale faisant référence à un article attend que sa version approuvée soit effectivement disponible sur le site. L'agent vérifie l'URL avant programmation.

## Exécution hebdomadaire sur Coolify

Proposition : préparer le plan le vendredi à 09:00, fuseau Europe/Paris, pour la semaine suivante. Après approbation du plan, produire les brouillons. Pas de dépendance à un ordinateur personnel. Les tâches existantes de publication Postiz restent responsables des envois sociaux.

État durable : semaine éditoriale, demandes prioritaires, sources et dates de consultation, fiches produits, version du plan, révisions de contenu, version de charte, médias, approbation horodatée, état et identifiant de publication par canal.

Clé de déduplication : organisation + semaine + créneau + canal + révision. Une relance ne crée pas de doublons. Un résultat d'envoi ambigu est vérifié avant toute nouvelle tentative. Une interruption reprend à la dernière étape terminée.

Limites initiales proposées : 7 sujets et 1 article par semaine ; deux tentatives de correction par contenu, puis signalement humain. Veille limitée aux sources autorisées et aux sujets utiles au magasin. Alertes seulement lorsqu'un lot est prêt, qu'une décision manque ou qu'une erreur bloque. Interrupteur global permettant de suspendre préparation et programmation.

## Vérification avant mise en service

- Test réel nom + identifiant avec sources et gestion des cas introuvables.
- Une semaine pilote complète produite en brouillons, avec trois produits distincts.
- Refus de publier sans approbation et refus de publier une révision modifiée.
- Prix masqué réellement absent du texte et du visuel ; prix explicite contrôlé.
- Produit visible conforme à sa photo, décor pertinent, texte lisible sur mobile.
- Relance sans doublon, reprise après erreur, changement d'heure Europe/Paris.
- Article correctement rendu sur mobile, liens valides, aucun brouillon dans le sitemap.
- Premier envoi réel uniquement pour un contenu explicitement approuvé.

## Ordre de réalisation

1. Corriger la recherche Internet du Postiz existant ; tester avec un produit réel.
2. Faire valider la charte et le fonctionnement sur la planche et ce plan.
3. Construire le dossier de recherche et la saisie des demandes ponctuelles, puis le plan hebdomadaire et ses validations.
4. Ajouter les gabarits visuels, la composition produit et les brouillons du blog ; exécuter la semaine pilote.
5. Activer la cadence après validation des essais, puis ajouter les statistiques quand les données suffisent.
