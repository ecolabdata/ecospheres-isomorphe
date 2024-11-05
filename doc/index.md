## Table des matières

- [Transformations disponibles](#transformations)
- [Pourquoi ISOmorphe ?](#pourquoi)
- [Comment fonctionne ISOmorphe ?](#comment)
- [Comment utiliser ISOmorphe ?](#tutoriel)

## <a name="transformations"></a>Transformations disponibles

<!-- insert:transformations_docs -->

## <a name="pourquoi"></a>Pourquoi ISOmorphe ?

Le moissonnage d'un catalogue INSPIRE par data.gouv.fr nécessite, lors du moissonnage, de convertir les fiches du catalogue d'origine ISO-19139/INSPIRE en un format compatible avec le modèle de données de data.gouv.fr.

La tendance de l'écosystème *open data* à converger vers le standard DCAT a amené data.gouv.fr à concentrer ses efforts sur la [prise en charge de ce dernier](https://doc.data.gouv.fr/moissonnage/dcat/). Ainsi, plutôt que de repartir de zéro, le moissonneur `csw-iso-19139` de data.gouv.fr s'appuie sur l'[algorithme de conversion ISO-19139 vers GeoDCAT-AP](https://github.com/SEMICeu/iso-19139-to-dcat-ap/tree/geodcat-ap-2.0.0) élaboré par le groupe de travail européen SEMICeu.

Si cette chaîne de conversion permet de prendre en charge efficacement les catalogues ISO-19139/INSPIRE, nous avons identifié des cas problématiques dont l'origine peut provenir (dans l'ordre du processus de conversion)&nbsp;:

1. du format des fiches d'origine, qui ne respectent pas toujours les subtilités du standard INSPIRE&nbsp;;
2. d'une limitation de l'algorithme SEMICeu, qui ne couvre pas encore l'ensemble des cas permis par INSPIRE&nbsp;;
3. d'une incompatibilité de représentation entre les standards ISO-19139 et GeoDCAT-AP, qui ne permet pas de convertir "parfaitement" une métadonnée&nbsp;;
4. d'une limitation du modèle de data.gouv.fr, qui ne prend que partiellement en charge le standard DCAT.

ISOmorphe se focalise sur les points 1 et 2 pour adapter les fiches des catalogues d'origine afin de maximiser les chances de succès des étapes suivantes.

Les transformations proposées par cet outil correspondent aux [recommandations ISO/DCAT](https://ecospheres.gitbook.io/recommandations-iso-dcat) formulées par Écosphères.

## <a name="comment"></a>Comment fonctionne ISOmorphe ?

ISOmorphe permet d'appliquer semi-automatiquement des *transformations* à un ensemble de fiches d'un catalogue Geonetwork, de manière à adapter la structure XML des fiches pour favoriser le moissonnage par data.gouv.fr, tout en préservant l'information saisie par les producteurs et la compatibilité avec ISO-19139/INSPIRE.

ISOmorphe ne fait rien qui ne pourrait être accompli manuellement par un administrateur ou un producteur de données en modifiant directement la structure de ses fiches via l'interface de Geonetwork. L'unique objectif de cet outil est de faciliter l'adaptation des fiches à l'échelle d'un catalogue entier.

Pour accéder aux fiches d'un catalogue et sauvegarder le résultat des transformations, ISOmorphe utilise l'API publique de Geonetwork. C'est la raison pour laquelle ISOmorphe demande de s'identifier sur le catalogue distant avec un compte possédant des droits suffisants pour modifier les fiches sélectionnées, soit a minima des droits d'édition.

Chaque transformation a été élaborée de manière à ce que les modifications de structure soient *ciblées* et *minimales*&nbsp;; ceci pour limiter les risques d'effets de bord, et laisser aux responsables de chaque catalogue un maximum de contrôle dans l'application des transformations.

Les transformations sont implémentées sous la forme de *Transformations XSL* (XSLT)&nbsp;; reprennant ainsi le mécanisme employé par SEMICeu pour implémenter l'algorithme de conversion ISO-19139 vers GeoDCAT-AP, et par Geonetwork pour des fonctionnalités telles que les "Suggestions" ou les "Transformations en batch". Une personne déjà familière des technologies employées dans cet écosystème peut donc si elle le souhaite analyser directement le code des transformations mises à disposition par ISOmorphe.
