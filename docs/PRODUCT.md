# Décision produit et périmètre du premier développement

Mis à jour le 2 octobre 2026. Les rapports de recherche distinguent preuves publiques, recommandations et hypothèses commerciales.

## Le problème retenu
Un dirigeant doit retrouver des pièces, vérifier des montants, répondre au comptable, suivre des créances et savoir ce qui manque avant une échéance. Le travail est réparti entre messagerie, fichiers et logiciels métier. Le produit prépare un dossier révisable, avec anomalies explicites et prochaine action interne.

La recherche recense 38 fonctions dans [la matrice des besoins](research/01-needs.md). Il ne s'agit pas d'un sondage démontrant que chaque fonction est détestée ni que le dirigeant paiera pour son automatisation. Les études et leurs limites sont documentées. La complexité réglementaire et les retards de paiement ressortent dans les sources institutionnelles ; l'ordre de réalisation reste notre hypothèse produit.

## Premier segment proposé
TPE de services B2B de 1 à 10 personnes, France ou Espagne, sans responsable administratif dédié, avec un outil de facturation et un expert-comptable ou une gestoría. Exemples : agence, cabinet de conseil, bureau d'études. Cette hypothèse doit être confrontée aux dossiers réels avant d'élargir aux secteurs à stocks, à paie complexe ou aux entreprises multi-pays.

## Livrables de la version initiale
| Compétence | Fonction livrée | Limite explicite |
|---|---|---|
| Qualification administrative | Orientation à partir du texte saisi et questions utiles | Heuristiques ; pas de boîte mail connectée |
| Contrôle de facture | Montants décimaux, HT/TVA/TTC, dates, champs et alertes | Une facture simple à un taux ; pas de contrôle exhaustif des mentions légales |
| Suivi des créances | Échéance et états saisis, brouillon interne sous conditions | Pas de rapprochement bancaire, pas d'envoi |
| Préparation comptable | Index de pièces structurées, doublons potentiels, comptage et totaux par devise | Les originaux ne sont pas téléversés ; aucun journal comptable certifié |
| Huit autres compétences | Checklists spécialisées, champs à réunir et pistes de contrôle | Modes guidés, pas d'automatisation métier complète |
| Assistance IA | Avis structuré optionnel avec références aux champs du dossier | Clé et modèle à configurer ; test réel fournisseur non réalisé lors de la livraison |

## Règles de confiance
- Le statut prêt correspond à une revue interne ; il ne veut jamais dire envoyé, payé, déposé ou signé.
- Un dossier incomplet ou en erreur ne peut pas être approuvé.
- Modifier une donnée invalide l'analyse et l'approbation précédentes.
- Les montants restent contrôlés par le code. Un modèle peut proposer un avis mais ne remplace pas les contrôles.
- Les entrées sont déclaratives : aucune saisie n'est une preuve de paiement ni d'existence d'une facture.
- Les règles FR et ES sont séparées et datées. Leur présence ne remplace pas la qualification du régime applicable.

## Différenciation à valider
La comparaison de sept solutions montre une forte couverture de la facturation, des justificatifs et de l'assistance IA. Notre hypothèse est de réduire le travail entre ces outils : exceptions expliquées, pièces reliées et dossiers utilisables par les professionnels en place. Mesurer le temps de revue est essentiel : un résultat produit vite mais long à corriger ne crée pas de valeur.

## Expérience pilote proposée
Préparer 30 à 50 dossiers consentis et anonymisés d'un seul processus, relever le temps manuel initial, puis comparer préparation, revue et correction. Séparer un lot de réglage et un lot d'évaluation jamais utilisé pour ajuster la skill. Aucune prospection ni prise de contact n'est lancée dans ce développement.

Mesures : exactitude des montants et dates, abstention sur les inconnues, minutes nettes évitées, corrections par dossier, coût humain et fournisseur, taux de dossiers prêts après revue. Le seuil commercial et les tarifs du rapport marché sont des hypothèses ; aucun revenu ou gain de temps n'est acquis.
