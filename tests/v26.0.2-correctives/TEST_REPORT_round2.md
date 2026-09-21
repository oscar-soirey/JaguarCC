# JaguarCC — campagne de correction ciblée (round 2)

Base analysée : `jcc(9).py` et la documentation Jaguar fournie. Les corrections ont été faites dans `jcc_fixed.py` / `jcc_fixed_round2.py`.

## 1. Fuite du `const` de méthode

### Reproduction
`focus/const_leak.ja` reprend le cas `Base` / `Derived` fourni.

Avec `jcc(9).py` :

```text
Jaguar Error: ...:21:9: a const method cannot modify member 'extra'
```

La ligne 21 est `extra = 0;` dans `destr()`.

### Cause réelle
Dans `CodeGen.gen_class`, `_current_class_method_const` est un état mutable du générateur.

La boucle des méthodes normales affectait cet état à chaque méthode. Lorsqu'elle terminait sur `get_value() const`, la valeur restait `True`. Le constructeur et le destructeur étant générés après cette boucle, le destructeur récupérait cet état contaminé et son écriture `extra = 0` était analysée comme une écriture depuis une méthode `const`.

Ce n'était donc pas un problème de résolution de `const`, ni de l'AST du destructeur : c'était une fuite d'état du CodeGen entre deux phases de génération d'une même classe.

### Correctif
- sauvegarde/restauration de `_current_class_method_const` autour de chaque méthode ;
- le constructeur commence explicitement avec `const = False` ;
- le destructeur commence explicitement avec `const = False` ;
- `_readonly_vars` est également isolé par méthode/constructeur/destructeur.

Le même test passe maintenant.

---

## 2. `map.size()` reconnu par le typage mais rejeté par le CodeGen

### Reproduction
`class_collections.ja` et `focus/collections_matrix.ja` utilisent :

```jaguar
return items.size() + prices.size() + data.size();
```

Avec `jcc(9).py` :

```text
Jaguar Error: ...:18:16: unknown function 'size'
```

### Cause réelle
Il y avait deux traitements séparés pour les appels de méthodes :

1. `infer_type()` connaissait déjà `map.size()` et lui attribuait `i32` ;
2. `gen_expr()` connaissait `dynamic_list.size()` et `list.size()`, mais pas `map.size()`.

Le typage pouvait donc réussir alors que l'émission C ne savait pas traduire l'appel. Le traitement tombait ensuite sur la résolution normale des fonctions et finissait sur `unknown function 'size'`.

C'est une incohérence entre l'analyse sémantique et le CodeGen.

### Correctif
Le CodeGen possède maintenant le cas `map::size` :

```text
(i32)<map>.size
```

Le test avec `list`, `map` et `dynamic_list` passe dans une même méthode `const`.

---

## 3. Collision C des méthodes surchargées

### Reproduction
`focus/calculator_overloads.ja` reprend exactement le `Calculator` fourni :

```jaguar
i32 $add(i32 x) { ... }
f64 $add(f64 x) const { ... }
```

La génération précédente produisait notamment :

```text
int32_t Calculator_add(Calculator *self, int32_t x)
double Calculator_add(Calculator *self, double x)
```

GCC signalait alors une collision de types sur `Calculator_add`.

### Cause réelle
Le resolver de méthodes distinguait déjà les deux signatures Jaguar, mais `_resolve_classes()` leur donnait le même nom C :

```text
Calculator_add
```

Le problème apparaissait donc uniquement au passage vers le langage cible. Ce n'était pas un échec de sélection d'overload.

### Correctif
Les méthodes réellement surchargées sont maintenant manglées par leurs types de paramètres :

```text
Calculator_add_i32
Calculator_add_f64
```

La résolution des appels utilise ensuite le même `mangled_name`, et les noms des entrées de vtable tiennent également compte de la signature.

Le programme `calculator_overloads.ja` compile avec GCC et s'exécute correctement.

---

## 4. Erreur dérivée détectée pendant le diagnostic : `list.get()`

Pendant la vérification de la matrice des collections, un problème de la même nature a été trouvé : l'analyse de type annonçait déjà `list.get()` comme valide, alors que le CodeGen et le traitement des appels n'étaient pas tous alignés.

Le comportement a été complété avec :

```jaguar
list<int> values = {1, 2, 3};
i32 x = values.get(1);
```

Le résultat est maintenant généré comme une lecture de l'élément du runtime `_j_list_get`.

Ce correctif n'enlève aucune fonctionnalité existante : il complète un chemin déjà accepté par l'analyse du compilateur.

---

## 5. `override` et `const`

Deux tests négatifs supplémentaires :

- base `virtual read() const` + dérivée `read() override` ;
- base `virtual read()` + dérivée `read() override const`.

Les deux sont maintenant rejetés comme overrides incompatibles.

La comparaison d'une signature d'override inclut désormais aussi `is_const`.

---

## 6. Tests de régression

### Positifs
Les fichiers suivants passent le compilateur Jaguar et le C produit est accepté par GCC :

- `advanced_structural.ja`
- `class_collections.ja`
- `docs_full_81.ja`
- `extras_new_overloads.ja`
- `reflection.ja`
- `signal_and_const.ja`
- `using_enums.ja`
- `virtual_overloads.ja`
- `focus/calculator_overloads.ja`
- `focus/collections_matrix.ja`
- `focus/const_leak.ja`
- `focus/focus_round2.ja`

`focus_round2.ja` combine dans un seul programme : classes/héritage/virtual/override/const, constructeurs/destructeurs, overloads de méthodes, enum, struct, union, namespaces imbriqués, `new`, `=>`, list/map/dynamic_list et `size()`/`get()`.

Il compile et s'exécute avec la sortie :

```text
5
6
7
10
12
12.5
30
21
2
60
true
12
```

### Négatifs
Les restrictions existantes continuent d'être rejetées, notamment :

- écriture dans une variable `const` ;
- écriture dans une méthode `const` ;
- écriture via pointeur vers `const` ;
- réaffectation d'un pointeur `const` ;
- écriture `list[]` / `map[]` ;
- syntaxe de références `&` dans les paramètres ;
- shadowing d'une globale ;
- `while` sans condition ;
- réflexion sur un `void*` arbitraire ;
- override avec incompatibilité `const`.

## Conclusion

Les trois erreurs fournies ont des causes distinctes et situées à trois niveaux différents :

1. état mutable contaminé dans le CodeGen de classe ;
2. divergence entre inférence sémantique et émission C pour une méthode de collection ;
3. résolution correcte mais name mangling incomplet au passage Jaguar -> C.

Les tests ciblés et la régression associée passent après correction, et un test négatif spécifique vérifie que le `const` d'un override incompatible n'est plus accepté.
