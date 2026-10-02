---
name: hr-onboarding
description: Préparer la coordination administrative de l'arrivée d'un salarié déjà choisi, avec liste de pièces et responsabilités. Utiliser pour l'onboarding RH, sans recrutement automatisé, paie, déclaration sociale ou traitement inutile de données sensibles.
---

# Préparer l'arrivée d'un salarié

## État du pilote

`guided` : checklist et préparation humaine ; aucune connexion paie, signature, déclaration, création de compte ou validation d'éligibilité à l'emploi. Le backend conserve `blocked`.

## Entrées et preuves

Demander référence pseudonymisée du dossier, employeur, pays/lieu de travail, date prévue, poste, responsable, type de contrat envisagé et liste des pièces déjà disponibles. Ne pas demander une copie d'identité, données de santé, coordonnées bancaires ou numéro social dans le texte envoyé au modèle.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md), puis uniquement [FR](../_shared/fr.md) ou [ES](../_shared/es.md) pour qualifier les démarches.
2. Vérifier si date d'arrivée et employeur sont confirmés. Distinguer salarié, prestataire et stagiaire ; ne pas imposer la même procédure.
3. Construire trois volets : pièces RH nécessaires, démarches réglementaires à faire vérifier, moyens opérationnels à préparer. Assigner un rôle responsable et une preuve attendue par ligne.
4. Pour toute date réglementaire, consulter la source officielle actuelle et le cadre applicable ; ne pas utiliser une échéance mémorisée comme preuve.
5. Marquer « disponible », « à vérifier » ou « manquant ». L'existence d'un fichier ne prouve pas sa validité ni une déclaration effectuée.
6. Proposer des accès minimaux correspondant au poste et une revue par le manager/IT. Ne pas créer de comptes ou accorder des droits.
7. Préparer une fiche de passation interne sans données personnelles superflues. Aucun jugement sur performance, aptitude, santé ou recrutement.

## Sortie JSON

Utiliser le contrat commun. `draft` liste pièce/action/responsable/preuve/date vérifiée ; `context` précise le périmètre et les sources réglementaires ; `missing_fields` contient les seules informations utiles. Conserver une erreur sur l'absence de contrôles métier implémentés et le statut `blocked`.

## Escalade et validation

Le responsable RH ou prestataire paie vérifie obligations, contrat et déclarations. Le manager valide les accès. Un sujet de droit au travail, santé, convention collective ou statut transfrontalier requiert une revue spécialisée ; ne pas conclure à l'éligibilité.

- Arrivée demain sans preuve de démarche sociale → point bloquant à vérifier, ne pas déclarer « embauche conforme ».
- Travailleur ES pour employeur FR → qualifier lieu/régime, aucune procédure FR automatique.
- Pièce contenant diagnostic médical → ne pas reproduire dans le briefing.
- Demande de classer des candidats → hors périmètre de ce skill.
