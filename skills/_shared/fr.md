# France : qualification avant application d'une règle

Ressource de routage, pas moteur de conformité. Sources ci-dessous ouvertes et contrôlées le **2026-10-02**. Reconsulter la page concernée au moment d'utiliser une obligation, un seuil ou un calendrier ; la date de consultation du guide ne prouve pas l'actualité ultérieure de la règle.

## Entrées de qualification

Demander seulement ce qui change la règle : forme juridique, activité, statut micro ou non, régime fiscal et TVA, assujettissement, établissement, taille pertinente, nature B2B/B2C/publique et nationale/internationale, période de l'opération, effectif si sujet social. Si inconnu, marquer `missing_fields` et ne pas extrapoler depuis une autre entreprise.

## Sources officielles par sujet

| Sujet | Source | Utilisation et limite |
|---|---|---|
| Mentions de facturation | [Service Public Entreprendre](https://entreprendre.service-public.gouv.fr/vosdroits/F31808) | Vérifier la forme d'entreprise et les mentions applicables ; la page distingue notamment les cas micro. Le payload minimal du pilote n'inclut pas toutes les mentions légales. |
| Calendrier de facturation électronique | [DGFiP : calendrier](https://www.impots.gouv.fr/professionnel/questions/partir-de-quand-suis-je-concerne-par-la-reforme-de-la-facturation) | Qualifier réception, émission et e-reporting séparément, selon taille et champ de l'opération ; relire le calendrier actuel avant de retenir une échéance. |
| Registre des traitements | [CNIL](https://www.cnil.fr/fr/RGPD-le-registre-des-activites-de-traitement) | Décrire finalités, catégories, destinataires, conservation et sécurité ; adapter aux traitements effectifs. Ne pas certifier la conformité. |
| Périmètre de la profession comptable | [Légifrance : ordonnance n° 45-2138](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000698851/) | Vérifier les articles et le cadre de la prestation avec un professionnel ; le pilote organise des pièces sans promettre une prestation autonome d'expertise comptable. |

Pour la TVA, l'électronique, les échéances, l'embauche et les déclarations, rechercher les pages actuelles de la DGFiP, d'Urssaf, de Net-entreprises, de Service Public et le texte applicable sur Légifrance. Les noms d'organismes sont des pistes de recherche ; aucune échéance n'est préchargée ici.

## Preuve à conserver par règle utilisée

`{country, topic, official_url, consulted_at, effective_from, scope, claim, source_excerpt_location, applicability_evidence}`. Les valeurs inconnues restent explicitement inconnues. Conserver une citation courte ou un repère de section, pas une copie intégrale. Une ancienne règle ne devient pas actuelle par simple réutilisation.

## Limites opérationnelles

Ne pas déduire un délai de paiement légal d'un délai contractuel saisi. Ne pas calculer pénalités, indemnités ou TVA déductible sans qualification et contrôle professionnel. Préparer les éléments pour le comptable, le juriste ou le responsable RH ; ne pas tenir une comptabilité certifiée, déposer une déclaration ou émettre un acte.
