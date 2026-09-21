# JaguarCC — rapport de modifications du 21 septembre 2026

## Périmètre de cette passe

Cette passe part de la version modifiée lors de la passe précédente et touche uniquement le compilateur pour les trois demandes suivantes :

1. déplacer `signal:` au niveau du corps de la classe ;
2. permettre la construction d'une `struct` par `Type(arg1, arg2, ...)`, sans introduire de constructeurs/destructeurs de struct ;
3. diagnostiquer dans JCC les opérateurs binaires qui n'existent pas pour les types utilisés, au lieu d'attendre un rejet de GCC.

La documentation officielle fournie n'a pas été modifiée.

## Source de vérité utilisée

Le compilateur réel reste la source de vérité. Son en-tête décrit le pipeline `Lexer -> Parser -> AST -> Resolver -> CodeGen` et son périmètre d'implémentation. La documentation jointe indique également qu'elle décrit l'implémentation courante de `jcc.py`, et pas une spécification future.

## 1. `signal:` au niveau de la classe

### Syntaxe ajoutée

La forme suivante est maintenant analysée comme une déclaration de la classe :

```jaguar
class Counter {
    $int value;

    signal: value {
        sys:print("changed");
    }
}
```

### Architecture

`ClassDecl` possède maintenant une collection dédiée de handlers de signaux de classe.

Le parser reconnaît `signal:` directement pendant le parsing du contenu d'une classe, avant de traiter les champs et méthodes.

Le handler n'est donc plus obligé d'être un statement d'une méthode pour cette nouvelle forme.

### Validation

Une déclaration de signal de classe doit désigner un champ existant de la classe ou de sa chaîne d'héritage.

Un signal qualifié tel que :

```jaguar
signal: MyClass:value { ... }
```

reste rejeté. La forme extérieure qualifiée n'est pas transformée en nouveau mécanisme.

### Génération

Les handlers de classe sont installés dans l'état sémantique de génération des méthodes de la classe. Une affectation à un champ correspondant déclenche alors le même mécanisme de comparaison de valeur que le `signal:` local existant.

Le handler est aussi actif pendant le corps des constructeurs/destructeurs de classe générés ; les initialisations automatiques des champs effectuées avant le corps du constructeur ne sont pas artificiellement transformées en événements supplémentaires.

### Runtime

Le scanner des built-ins système prend désormais aussi en compte les expressions contenues dans les handlers de signaux de classe. Cela évite qu'un `sys:print()` présent uniquement dans un signal de classe produise un symbole runtime manquant.

### Test exécuté

Exemple : `class_signal_requested.ja`

```jaguar
class Counter {
    $int value;

    signal: value {
        sys:print("changed");
    }

    $void run() {
        value = 1;
        value = 1;
        value = 2;
    }
}

void main() {
    Counter c = Counter();
    c.run();
}
```

Résultat observé :

```text
changed
changed
```

Le second affichage correspond à `1 -> 2`. L'affectation `1 -> 1` ne déclenche pas le handler.

## 2. Construction de `struct` avec arguments

### Syntaxe ajoutée

La forme demandée fonctionne maintenant :

```jaguar
struct v2 {
    int a;
    int b;
}

void main()
{
    v2 a = v2(3,5);
}
```

### Règle implémentée

Pour une struct ayant `N` champs, `Type(...)` accepte exactement `N` arguments positionnels.

Les arguments sont affectés aux champs dans l'ordre de leur déclaration.

Exemple :

```text
v2(3, 5)
       -> a = 3
       -> b = 5
```

Les arguments sont vérifiés avec le même contrôle d'assignation déjà utilisé ailleurs dans le compilateur.

Les arguments nommés ne sont pas acceptés pour cette construction ; ce n'est pas une fonctionnalité demandée et aucune nouvelle sémantique de constructeur nommé n'a été inventée.

La forme `v2()` sans argument reste disponible et conserve la construction zéro-initialisée existante.

### C généré

JCC génère une petite fonction interne de construction par valeur, par exemple conceptuellement :

```c
static v2 _j_struct_v2_make(...)
{
    v2 value;
    value.a = ...;
    value.b = ...;
    return value;
}
```

Le choix d'un helper C plutôt qu'un compound literal permet de conserver cette nouvelle syntaxe aussi en mode `--c89`.

### Constructeurs/destructeurs de struct

Aucun mécanisme `constr`/`destr` n'a été ajouté aux structs.

Les tests suivants sont toujours rejetés :

```jaguar
struct v2 {
    int a;
    constr() { }
}
```

et :

```jaguar
struct v2 {
    int a;
    destr() { }
}
```

Les deux produisent encore une erreur de parsing au niveau de `constr`/`destr`.

### Tests exécutés

`struct_constructor_requested.ja` :

```text
3
5
```

Compilation/exécution normale : succès.

Compilation/exécution avec `--c89` : succès, sortie identique :

```text
3
5
```

Erreur de nombre d'arguments :

```text
struct 'v2' construction expects 2 argument(s), 1 provided
```

Erreur de type :

```text
type mismatch: cannot assign 'string' to 'i32' (initializer for struct field 'a')
```

Ces diagnostics sont produits par JCC avant l'étape GCC.

## 3. Détection des opérateurs inexistants

Le compilateur possédait déjà la résolution des opérateurs utilisateur ajoutée lors de la passe précédente.

La vérification a donc été ajoutée juste autour du chemin existant :

1. JCC cherche d'abord une surcharge Jaguar `operator<op>` applicable ;
2. si une surcharge existe, elle est conservée ;
3. sinon, JCC vérifie si l'opérateur intégré est défini pour les types concernés ;
4. lorsque ce n'est pas le cas, JCC lève directement un diagnostic `no operator exists ...`.

### Cas ajouté explicitement

Pour :

```jaguar
struct v2 {
    int a;
}

void main() {
    v2 a = v2(1);
    v2 b = v2(2);
    v2 c = a + b;
}
```

JCC donne :

```text
no operator exists for 'v2' + 'v2'
```

Pour :

```jaguar
bool x = a == b;
```

sans `operator==` défini, JCC donne :

```text
no operator exists for 'v2' == 'v2'
```

### Surcharge valide

Une déclaration :

```jaguar
bool operator==(v2 a, v2 b) {
    return a.a == b.a;
}
```

continue de fonctionner.

Le test existant de surcharge `operator==` retourne bien `1`, et le test `operator+` retourne bien `5`.

### Pas de nouveau mot-clé `operator`

`operator` n'a pas été transformé en mot-clé global. Le compilateur continue de permettre un identifiant nommé `operator` dans un contexte ordinaire.

Le test existant correspondant continue de produire `5`.

## 4. Régression complète après les changements

Les 10 programmes de référence de la passe précédente ont été recompilés avec l'ancien compilateur puis avec le compilateur actuel.

Pour chaque programme, la sortie d'exécution a été comparée octet par octet via `diff`.

Résultat :

```text
10/10 PASS — sorties identiques avant/après
```

Les exemples concernés comprennent notamment :

- `basic.ja`
- `c89.ja`
- `class.ja`
- `collections.ja`
- `forloop.ja`
- `if_not.ja`
- `namespace.ja`
- `overload.ja`
- `pointer.ja`
- `signal_local.ja`

## 5. Re-test des fonctionnalités ajoutées lors de la passe précédente

Les exemples valides précédents ont également été recompilés et exécutés :

- décorateurs personnalisés ;
- paramètres de décorateurs ;
- signal membre dans l'ancienne forme de test ;
- signal `string` ;
- `operator==` utilisateur ;
- `operator+` utilisateur ;
- identifiant `operator` ordinaire ;
- multithreading `thread:*`.

Tous les cas valides testés ont réussi.

Les cas invalides suivants continuent d'être rejetés :

- signal membre qualifié hors classe ;
- opérateur utilisateur avec mauvais nombre de paramètres ;
- `thread:start` avec un callback incompatible.

## 6. Vérification Python

Les trois fichiers livrés passent `py_compile` :

```text
jcc.py
jbs.py
jlanguage_server.py
```

Le fichier JBS et le language server n'ont pas reçu de changement fonctionnel dans cette passe ; ils sont livrés dans l'état modifié de la passe précédente afin que le pack reste cohérent.

## 7. Environnement de test et limites

Le dossier fourni ne contient pas le GCC embarqué attendu à côté de JCC.

Pour les tests end-to-end, un environnement temporaire a donc exposé `/usr/bin/gcc` sous :

```text
toolchain/bin/gcc
```

Ce lien symbolique n'est pas une modification du compilateur livré.

Les tests d'exécution effectués ici démontrent le backend utilisé dans cet environnement Linux. Le backend Windows du runtime thread n'est pas déclaré comme testé sur Windows dans ce rapport.

## 8. Documentation

`JaguarCC_docs_EN(1).md` n'a pas été modifiée.

Elle reste le document officiel fourni utilisé comme référence complémentaire ; le compilateur réel est resté l'autorité pour décider de la syntaxe et du comportement effectivement testables.

## 9. Fichiers livrés

Le pack contient :

```text
compiler/jcc.py
compiler/jbs.py
compiler/jlanguage_server.py

examples/before/*
examples/after/*
examples/new/*

logs/*
README.md
RAPPORT_MODIFICATIONS.md
```

Les exemples `.ja` utilisés pour les tests sont conservés dans le pack afin de permettre une reproduction locale des vérifications.
