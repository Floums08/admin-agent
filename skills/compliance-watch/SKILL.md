---
name: compliance-watch
description: Préparer un inventaire de preuves et d'écarts administratifs de conformité, notamment pour les données personnelles et les prestataires. Utiliser pour organiser les questions et responsabilités, sans certifier la conformité ou rédiger un avis juridique définitif.
---

# Organiser les preuves de conformité

## État du pilote

`guided` : dossier préparatoire ; pas d'audit exhaustif, analyse d'impact automatique, veille périodique ou certification. Le backend conserve `blocked`.

## Entrées et preuves

Définir thème, entité, pays, activités concernées, finalités de traitement, catégories de personnes/données, prestataires, accès, destinations, conservation, mesures existantes et documents datés. Ne pas importer les données personnelles réelles lorsque leurs catégories suffisent.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md), puis [FR](../_shared/fr.md) ou [ES](../_shared/es.md) selon le dossier. Utiliser CNIL/AEPD et les textes officiels actuels pour les exigences discutées.
2. Fixer un périmètre limité : par exemple gestion clients ou collecte de justificatifs. Ne pas qualifier toute l'entreprise sur l'analyse d'un formulaire.
3. Pour chaque finalité, inventorier catégories, destinataires, rôle responsable/sous-traitant, conservation et mesures déclarées ; distinguer déclaration et preuve consultée.
4. Pour chaque exigence applicable, associer source, preuve, écart, responsable et action de préparation. Une politique écrite n'atteste pas à elle seule son application technique.
5. Vérifier les dépendances prestataires : contrat, instructions, sous-traitants, lieux de traitement et mesures de sécurité à documenter. Ne pas conclure que « hébergé en UE » couvre toutes les obligations.
6. Identifier données sensibles, surveillance ou traitement à risque pour orientation vers une analyse spécialisée ; ne pas affirmer qu'un outil simplifié de conformité suffit.
7. Produire un registre de questions prioritaires et un inventaire de preuves ; éviter tout score de conformité en pourcentage non fondé.

## Sortie JSON

Utiliser le contrat commun. `draft` porte l'inventaire exigence/preuve/écart/action ; `context.evidence` associe les constats aux documents et sources ; `missing_fields` indique les preuves absentes. `findings` rappelle le contrôle métier non implémenté ; le statut reste `blocked`.

## Escalade et validation

Le dirigeant assume les décisions avec son conseil/DPO selon le besoin. Violation de données suspectée : signaler au responsable et documenter les faits nécessaires ; ne pas contacter autorité, client ou salarié et ne pas inventer de délai applicable sans qualification.

- Politique RGPD fournie sans preuve de sécurité → conformité non démontrée.
- Sous-traitant sans contrat → manque visible, aucun contrat réputé signé.
- Données de santé → revue spécialisée, pas validation automatique via outil simplifié.
- Documentation espagnole et traitement FR → vérifier juridiction, ne pas copier mécaniquement les obligations.
