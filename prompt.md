##### Features:

//-signal sur une variable membre de classe

\-convertir une api complete, pas juste un single file

//-surcharge d'operateurs avec MyStruct operator==(MyStruct a, MyStruct b) { return ...; }

//-multithreading

//-syntaxe if(!condition)

\-operateur + sur les strings



**Petites features sympa mais pas vraiment obligés:**

\-faire un installateur custom pour installer python 3.14 si besoin, detecter si on a vscode, et installer l'extension si besoin.



**Bugs connus:**

\-si le fichier jbs s'appelle juste .jbs, il le trouve pas, je veux que ca puisse marcher









##### Stabilité:

\-produire un IR intermediaire

\-ecris la lib jcc en C (avec les vraies fonctions C), et utiliser Jaguar Bindgen pour l'api jcc

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

\-icone jaguar dans l'installer au lieu de l'icone par defaut









##### Livre:

\-parler de l'extension vscode

\-crimson et intégration à jbs

\-histoire du langage (ca a été crée par moi meme qui est un developpeur de jeux videos/moteurs de jeux, et que pleins d'aspects pourraient etre natifs au langage, mais tu dois passer par des galeres pour les ajouter en c++ par exemple.

le langage corrige les defaut du C++ qui sont vraiment chiant dans un moteur: factory native, reflexion native, container<>, signal:, dynamic\_list qui remplacent des aspects super chiants du C++ (lambdas, variant ou union, macros complexes, et plus)

