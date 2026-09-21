# Rapport détaillé — JaguarCC / JBS / Language Server — 2026-09-21

## 1. Base d'analyse

L'analyse a été faite à partir des trois sources Python fournies (`jcc.py`, `jbs.py`, `jlanguage_server.py`) et de la documentation officielle fournie, en prenant `jcc.py` comme source de vérité d'implémentation.

Le compilateur décrit lui-même son pipeline comme Lexer -> Parser -> Resolver -> CodeGen, et précise que le périmètre documenté correspond à ce qui est réellement implémenté. La documentation fournie indique également explicitement qu'elle décrit l'implémentation courante, pas une spécification future.

La documentation officielle n'a pas été modifiée.

## 2. Principe de stabilité

Avant les ajouts, un jeu de 10 programmes Jaguar couvrant les fonctions existantes a été exécuté avec la version originale du compilateur.

Après les ajouts, les mêmes 10 programmes ont été exécutés avec le compilateur modifié.

Pour chaque exemple, le code de retour, le stade d'exécution et la sortie standard observée avant/après correspondent exactement. Ce contrôle inclut notamment le test existant de `if(!condition)` et un test en `--c89`.

Résultats de régression : 10/10 identiques avant/après.

## 3. Décorateurs personnalisés

### Syntaxe ajoutée

La forme demandée est reconnue :

```jaguar
void @announce(string label):func {
    sys:print(label);
    func();
    sys:print("after");
}

@announce("before")
void hello() {
    sys:print("inside");
}
```

### Implémentation

- ajout d'AST pour l'utilisation d'un décorateur et pour sa déclaration ;
- parsing de `void @nom(params):func { ... }` ;
- résolution des décorateurs par namespace ;
- vérification des arguments du décorateur ;
- génération d'une implémentation interne pour la fonction décorée ;
- génération des wrappers qui exécutent le corps du décorateur ;
- `func()` dans le corps du décorateur appelle la cible/wrapper suivante avec les paramètres de la fonction décorée.

### Limite volontaire

Une fonction décorée doit actuellement être `void`, non `@extern` et non un simple prototype. Cette restriction évite d'inventer un mécanisme de retour dans une syntaxe de wrapper qui ne fournit pas d'opération de retour autour de `func()`.

### Tests

- `decorator.ja` -> succès, sortie : `before / inside / after`.
- `decorator_args.ja` -> succès, vérifie la transmission des paramètres de la fonction décorée : `wrap / 7`.

## 4. `signal:` sur variable membre de classe

Le comportement existant des signaux sur variables locales/globales a été conservé.

### Nouvelle forme fonctionnelle

Dans une méthode de classe :

```jaguar
class Counter {
    $int value;

    $void run() {
        signal: value {
            sys:print("changed");
        }

        value = 1;
        value = 1;
        value = 2;
    }
}
```

Le handler est déclenché lorsque l'affectation à `this.value` modifie réellement la valeur. Dans le test, la deuxième affectation de `1` ne déclenche pas le handler, tandis que le passage `0 -> 1` puis `1 -> 2` le déclenche.

### Contrôle de portée

La forme qualifiée demandée depuis l'extérieur :

```jaguar
signal: Counter:value {
    ...
}
```

est rejetée avec le diagnostic :

`signal on a class member is only valid inside the class; use `signal: field``

Cela empêche d'exposer le mécanisme de signal membre hors du contexte de la classe.

### Chaînes

Un test supplémentaire vérifie aussi un champ `string`. La comparaison utilise le contenu des chaînes afin de conserver la même règle que les signaux déjà existants sur `string`.

### Tests

- `member_signal.ja` -> succès, sortie : `changed / changed`.
- `member_signal_string.ja` -> succès, sortie : `a / b`.
- `member_signal_outside.ja` -> échec attendu avec diagnostic ciblé.

## 5. Surcharge d'opérateurs

### Syntaxe ajoutée

La forme demandée est reconnue :

```jaguar
MyStruct operator==(MyStruct a, MyStruct b) {
    ...
}
```

### Implémentation

- ajout du parsing des déclarations `operator<op>` ;
- validation à la résolution : un opérateur binaire déclaré doit avoir exactement deux paramètres ;
- conversion du nom logique en identifiant C valide pour le nom généré (`operator_eq`, etc.) ;
- résolution d'un opérateur utilisateur avant le comportement primitif existant ;
- l'expression prend le type de retour de la fonction opérateur ;
- émission d'un appel à la fonction opérateur lorsqu'une surcharge correspondante est trouvée.

Les opérateurs binaires couverts par le mécanisme sont `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `<=`, `>=`.

La résolution de ces opérateurs ne change pas les règles générales de typage : elle vérifie les types logiques des deux opérandes.

### Stabilité particulière

`operator` n'a pas été transformé en mot-clé réservé global. Un test séparé confirme qu'un identifiant Jaguar existant nommé `operator` continue de fonctionner.

### Tests

- `operator_eq.ja` -> succès, sortie `1`.
- `operator_plus.ja` -> succès, sortie `5`.
- `operator_bad_arity.ja` -> échec attendu avec `operator '==' requires exactly 2 parameters`.
- `operator_identifier.ja` -> succès, sortie `5`.

## 6. `if(!condition)`

Aucune nouvelle implémentation n'a été ajoutée ici : cette syntaxe était déjà couverte par le lexer/parser/codegen existants sous forme d'opérateur unaire `!` et de `if (...)`.

Le choix de stabilité a donc été de ne pas modifier cette chaîne de compilation et de la traiter comme une régression obligatoire.

Le test `if_not.ja` produit la même sortie `not` avant et après.

## 7. Multithreading natif — namespace `thread:`

Un runtime natif a été ajouté directement au compilateur, sans package Jaguar à importer.

### API actuellement implémentée

```text
thread:start(fn() -> void) -> void*
thread:join(void*) -> void
thread:detach(void*) -> void
thread:sleep(int milliseconds) -> void
thread:yield() -> void
```

### Backend

- Windows : primitives natives de Windows (`CreateThread`, `WaitForSingleObject`, `Sleep`, `SwitchToThread`).
- POSIX/Unix-like : `pthread_create`, `pthread_join`, `pthread_detach`, `nanosleep`, `sched_yield`.
- Sur POSIX, la génération finale ajoute `-pthread` lorsque le runtime thread est utilisé, car cette API système nécessite le lien correspondant.

### Contrôles de type

`thread:start` exige actuellement un callback de type exact `fn() -> void`.

`thread:join` et `thread:detach` exigent un handle `void*` (ou `nullptr`).

`thread:sleep` exige un entier.

### Tests

- `thread.ja` -> succès, sortie observée `worker / main`.
- `thread.ja` en `--c89` -> succès, même sortie.
- `thread_wrong.ja` -> échec attendu avec diagnostic sur le type du callback.

## 8. Bug JBS : fichier nommé exactement `.jbs`

Le fichier `jbs.py` refusait auparavant le nom littéral `.jbs`, car le suffixe de `Path('.jbs')` n'est pas `.jbs`.

Le correctif :

- accepte explicitement `jbs_path.name == '.jbs'` ;
- lorsque JBS est lancé sans argument de projet, il recherche un fichier `.jbs` dans le répertoire courant et l'utilise lorsqu'il existe.

### Tests

- ancienne version + `python jbs.py .jbs` -> échec attendu avant correction ;
- version modifiée + `python jbs.py .jbs` -> succès ;
- version modifiée + `python jbs.py` depuis le répertoire contenant `.jbs` -> succès.

## 9. Language Server

Le language server continue d'utiliser le lexer/parser de JCC lorsqu'il peut parser le document, avec son scan tolérant pour les buffers incomplets.

Les ajouts côté LSP sont volontairement ciblés :

- signatures de `thread:*` pour completion/hover ;
- completion après `thread:` ;
- aucune réservation de `operator`, pour rester cohérent avec le compilateur qui le traite comme identifiant ordinaire hors syntaxe d'opérateur.

Tests : chargement du JCC modifié réussi et completion `thread:` contenant `detach`, `join`, `sleep`, `start`, `yield`.

## 10. Vérification de syntaxe Python

Les trois fichiers modifiés passent :

```text
python3 -m py_compile jcc_modified.py jbs_modified.py jlanguage_server_modified.py
```

## 11. Limitation de l'environnement de test

Le dossier fourni ne contenait pas le `toolchain/bin/gcc` de la distribution Jaguar attendue par JCC.

Pour les tests end-to-end, un environnement temporaire de test a donc exposé `/usr/bin/gcc` sous le chemin `toolchain/bin/gcc` attendu par le compilateur. Cette adaptation n'a pas été intégrée dans les sources modifiées.

## 12. Fichiers livrés

- `compiler/jcc.py` — compilateur modifié ;
- `compiler/jbs.py` — JBS modifié ;
- `compiler/jlanguage_server.py` — language server modifié ;
- `examples_before/` — 10 régressions avant/après ;
- `examples_after/` — exemples valides et invalides des nouvelles fonctionnalités ;
- `final_jcc_tests.txt` — journal des régressions et principaux tests de fonctionnalités ;
- `final_jcc_extra_tests.txt` — tests complémentaires ;
- `final_jbs_tests.txt` — tests `.jbs` ;
- `final_lsp_tests.txt` — tests LSP.

Aucun fichier de documentation officiel n'a été réécrit.
