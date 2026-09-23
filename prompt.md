##### Features:

\-nouvelle syntaxe pour gerer les build (.b)



**Petites features sympa mais pas vraiment obligés:**

\-faire un installateur custom pour installer python 3.14 si besoin, detecter si on a vscode, et installer l'extension si besoin.



**Bugs connus:**









##### Stabilité:

\-produire un IR intermediaire

\-diviser le compilateur en pleins de scripts dans un dossier script/ et garder le point d'entré à jcc.py









##### Extension VS Code:

\-ast visualiser dans vscode

\-detecter les commentaires au dessus des fonctions, variables et autres les afficher formattés quand on survole l'item

\-tout comme les path en .jbs sont hint, je veux aussi que ca me proprose les fichiers avec using dans les .ja (on trouve cherche à la racine du .ja et dans les include path donnés a include directive en jbs



**Bugs connus:**

\-build et build \& run ouvrent a chaque fois un nouveau terminal vscode, utiliser toujours le terminal courant si il est a la racine du projet







##### Plus tard:

\-jbs doit gerer c -> jaguar, mais aussi jaguar -> c

\-extension pour Jetbrains et Visual Studio

\-en mode debug, ecrire toutes les operations réalisées au runtime, et donc ne pas generer le meme code c en debug et en release









##### Petites corrections:











##### Livre:

\-parler de l'extension vscode (pour l'installer au lien suivant : https://marketplace.visualstudio.com/items?itemName=OscarSoirey.jaguar-language) ou alors on peut l'installer directement depuis vscode en cherchant Jaguar dans les plugins

\-crimson et intégration à jbs

\-histoire du langage (ca a été crée par moi meme qui est un developpeur de jeux videos/moteurs de jeux, et que pleins d'aspects pourraient etre natifs au langage, mais tu dois passer par des galeres pour les ajouter en c++ par exemple.

le langage corrige les defaut du C++ qui sont vraiment chiant dans un moteur: factory native, reflexion native, container<>, signal:, dynamic\_list qui remplacent des aspects super chiants du C++ (lambdas, variant ou union, macros complexes, et plus)

\-couleur d'accent en vert foncé Jaguar

\-inclure le logo jaguar et le nom Oscar Soirey

\-ajouter un section spéciale pour creer un jeu avec sdl2, de A à Z (jeu simple bien sur)



\-changer la police de titre à

\-changer la police de code à

\-changer la police de corps à

