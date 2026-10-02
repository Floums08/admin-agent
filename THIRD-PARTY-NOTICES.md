# Composants tiers et notices

Inventaire ajouté le 2 octobre 2026 pour l'OCR et les connecteurs gratuits. Ce fichier indique les composants utilisés et leurs sources ; il n'attribue pas de licence nouvelle au code du dépôt et ne remplace pas les textes de licence livrés par chaque composant.

| Composant | Usage réel | Licence / source officielle | Notices conservées |
|---|---|---|---|
| Tesseract OCR et données de langue | Reconnaissance de texte imprimé FR/ES/EN dans le worker | [Apache 2.0, documentation officielle](https://tesseract-ocr.github.io/tessdoc/) ; [source du moteur](https://github.com/tesseract-ocr/tesseract) | Paquets Debian : `/usr/share/doc/tesseract-ocr/copyright` et répertoires des paquets `tesseract-ocr-*` ; texte sous `/usr/share/common-licenses/Apache-2.0` |
| Poppler utilities et bibliothèques associées | Lecture du texte et rendu des PDF par exécutables distincts | [Projet et code source](https://poppler.freedesktop.org/) ; licence GPL, versions et exceptions précisées dans le copyright du paquet | `/usr/share/doc/poppler-utils/copyright`, notices des bibliothèques et `/usr/share/common-licenses/` dans l'image |
| Pillow | Lecture et validation des images | [MIT-CMU, documentation officielle](https://pillow.readthedocs.io/en/stable/about.html#license) ; [source](https://github.com/python-pillow/Pillow) | Métadonnées et fichier de licence installés par pip dans `Pillow`/`pillow-*.dist-info/` |
| Nextcloud Server | Service externe facultatif joint via WebDAV ; pas embarqué dans l'image | [AGPL v3 ou ultérieure, selon les fichiers](https://github.com/nextcloud/server/blob/master/COPYING-README) ; [source](https://github.com/nextcloud/server) | Administrateur de l'instance Nextcloud responsable de la distribution et de ses notices |
| Dolibarr ERP/CRM | Service externe facultatif joint via API REST ; pas embarqué dans l'image | [GPL v3 ou ultérieure](https://wiki.dolibarr.org/index.php/FAQ_Cu%C3%A1l_es_la_licencia_Dolibarr_%3F) ; [source](https://github.com/Dolibarr/dolibarr) | Administrateur de l'instance Dolibarr responsable de sa distribution et de ses notices |

Le Dockerfile OCR ne supprime ni `/usr/share/doc`, ni `/usr/share/common-licenses`, ni les métadonnées de licence Python. Les versions système proviennent des dépôts maintenus de Debian Bookworm lors du build. Le manifeste de paquets créé dans `/app/ocr-packages.txt` et le digest d'image identifient ce qui a été livré ; les versions des essais sur une autre distribution ne doivent pas lui être substituées.

Pour distribuer une image contenant ces exécutables, conserver ses notices et fournir les sources correspondantes selon les licences applicables, notamment celles de Poppler et de ses dépendances GPL. Les références amont, versions de paquets et archives de sources sont à conserver avec la livraison. Utiliser des paquets sans redevance ne signifie pas que leurs conditions de redistribution disparaissent.

Les autres dépendances de production restent décrites dans `requirements-production.txt` et dans leurs métadonnées de distribution. Les bibliothèques de test npm sont décrites dans `package-lock.json` ; elles ne sont pas livrées au navigateur. Le présent ajout ne remplace pas un inventaire complet de toutes les bibliothèques système transitives.
