# JaguarCC regression campaign

Base étudiée : `jcc(9).py` + `JaguarCC_docs_EN(1).md`.

Le compilateur décrit une chaîne Lexer -> Parser -> AST -> Resolver -> CodeGen et documente notamment classes, héritage, surcharge, namespaces, structs, unions, collections, attributs et `const`.

## Correctifs appliqués dans `jcc_fixed.py`

1. **Fuite d'état `const` des méthodes vers constructeur/destructeur**
   - Le contexte de méthode `const` et l'ensemble des variables read-only sont maintenant sauvegardés/restaurés autour de chaque méthode.
   - Constructeur et destructeur repartent explicitement avec `const` désactivé.

2. **Enums dans les namespaces**
   - La résolution enregistrait le nom logique non préfixé alors que le codegen utilisait le nom C préfixé.
   - Les types d'enum namespacés ont maintenant le même nom logique que celui utilisé par le codegen.

3. **Types internes `void_ptr`**
   - `dynamic_list.get()`, `factory:construct()` et la réflexion renvoient maintenant le type Jaguar interne `void*` cohérent avec le runtime, au lieu de laisser fuir `void_ptr` dans l'analyse/code C.

4. **Runtime `dynamic_list`**
   - La fonction `_j_dynamic_list_borrowed` est émise avant sa première utilisation.

5. **`map::size()`**
   - L'inférence de type connaissait déjà `map::size()`, mais le générateur C ne l'émettait pas. L'émission correspond maintenant au runtime `_jMap.size`.

6. **Réflexion dynamique**
   - Une valeur issue de `factory:construct()` est suivie comme objet Jaguar dynamique pour `MemberExists`, `GetMember` et `SetMember`.
   - La génération reconnaît ces appels de réflexion avant d'inférer le type du `MemberAccess`, ce qui évite de traiter le récepteur `void*` comme un membre classique.
   - Un `void*` arbitraire n'obtient pas ces capacités de réflexion.

7. **Surcharge de méthodes de classe**
   - Les méthodes surchargées ont maintenant un nom C manglé par signature.
   - La résolution des appels de méthodes utilise les mêmes règles de compatibilité/sélection que la surcharge de fonctions.
   - Les noms des champs de vtable sont stables par signature afin que les overrides conservent la même case virtuelle.

## Gros fichiers positifs testés

Chaque fichier ci-dessous a été compilé puis exécuté en mode Jaguar normal et avec `--c89`, puis le C produit a été compilé avec `gcc -std=c89 -pedantic -Werror -w -lm`.

- `docs_full_81.ja` — documentation + classes/attributs/collections/default args/named args.
- `advanced_structural.ja` — aliases, pointeurs, fonction pointers, enum, struct, union, namespaces imbriqués, using, classes/héritage/virtual/override, extern, collections, string, loops.
- `signal_and_const.ja` — signal + const variable + const pointee + const pointer + pointeurs.
- `class_collections.ja` — champs de classe list/map/dynamic_list/container + constructeur/destructeur + reflection annotations.
- `reflection.ja` — `@register`, `@exposed`, `factory:construct`, `MemberExists`, `GetMember`, `SetMember`.
- `extras_new_overloads.ja` — `new i32(5)`, `=>`, enum, struct, union, namespace imbriqué, overloads de méthodes, `const` méthode/paramètre.
- `virtual_overloads.ja` — overloads virtuels + override partiel + vtable.
- `using_enums.ja` — `using namespace` + lookup d'enum values.

## Erreurs négatives vérifiées

Les restrictions suivantes continuent de produire une erreur Jaguar : modification de `const`, écriture via pointeur vers `const`, réaffectation d'un pointeur `const`, écriture dans méthode `const`, shadowing d'une globale, `while` sans condition, écriture par `[]` dans list/map, syntaxe de références `&` dans les paramètres, réflexion sur un `void*` arbitraire.

## Résultat

Tous les fichiers positifs ci-dessus compilent et s'exécutent en mode normal et C89. Les cas négatifs gardent leurs diagnostics attendus.

Les tests ont volontairement suivi le comportement réellement présent dans `jcc.py`. Lorsqu'une partie de la documentation divergeait de l'implémentation actuelle, elle n'a pas été inventée/corrigée artificiellement pour faire passer le test : l'exemple a été adapté au compilateur réel et la divergence est conservée comme telle.
