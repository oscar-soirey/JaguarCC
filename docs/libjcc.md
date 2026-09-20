# libjcc — Bibliothèque standard de Jaguar

`libjcc` est la bibliothèque standard fournie directement par **JaguarCC (`jcc`)**.

Elle expose une sélection volontairement simple de fonctionnalités courantes de la libc et de `math.h`, mais avec des conventions adaptées à Jaguar :

- les fonctions sont accessibles dans le namespace `jcc` ;
- les chaînes utilisent le type Jaguar `string`, et non `char*` ;
- les pointeurs ne sont pas exposés dans cette API ;
- les fonctions compliquées de la libc qui nécessitent une gestion manuelle de mémoire ou de pointeurs ne sont pas incluses ;
- les noms sont explicites et suivent les conventions Jaguar plutôt que de reproduire directement les noms C ;
- le runtime C nécessaire est généré automatiquement par `jcc`.

> **Exemple**
>
> ```jaguar
> void main(string param) {
>     f64 value = jcc:sqrt(25.0);
>     sys:print(value);
> }
> ```

---

## Sommaire

1. [Principes](#principes)
2. [Contrôle du programme](#contrôle-du-programme)
3. [Entiers et utilitaires](#entiers-et-utilitaires)
4. [Temps](#temps)
5. [Mathématiques](#mathématiques)
6. [Chaînes](#chaînes)
7. [Conversions](#conversions)
8. [Caractères](#caractères)
9. [Fichiers](#fichiers)
10. [Variables d'environnement](#variables-denvironnement)
11. [Exemple complet](#exemple-complet)
12. [Fonctions non exposées](#fonctions-non-exposées)
13. [Compatibilité C89](#compatibilité-c89)

---

# Principes

## Namespace `jcc`

Toutes les fonctions de cette bibliothèque utilisent le namespace `jcc`.

```jaguar
jcc:sqrt(16.0);
jcc:abs_i32(-42);
jcc:string_length("Hello");
```

Le namespace permet d'éviter de mélanger les fonctions de la bibliothèque avec les fonctions définies par l'utilisateur.

---

## Types utilisés

La bibliothèque utilise principalement les types Jaguar suivants :

| Type | Utilisation |
|---|---|
| `i32` | Entier signé 32 bits |
| `i64` | Entier signé 64 bits |
| `f64` | Nombre flottant 64 bits |
| `bool` | Booléen |
| `string` | Chaîne Jaguar |
| `void` | Aucun retour |

Les caractères sont représentés par des `i32` correspondant à leur valeur numérique ASCII/locale C.

---

# Contrôle du programme

## `jcc:exit`

Termine immédiatement le programme avec un code de sortie.

### Signature

```jaguar
i32 jcc:exit(i32 code)
```

### Exemple

```jaguar
void main(string param) {
    jcc:exit(0);
}
```

Un code `0` est généralement utilisé pour indiquer une terminaison normale.

---

## `jcc:abort`

Arrête immédiatement le programme de manière anormale.

### Signature

```jaguar
void jcc:abort()
```

### Exemple

```jaguar
void main(string param) {
    jcc:abort();
}
```

Cette fonction appelle directement le mécanisme d'abandon du runtime C.

---

## `jcc:assert`

Vérifie une condition. Si elle est fausse, le programme est interrompu et le message est affiché.

### Signature

```jaguar
void jcc:assert(bool condition, string message)
```

### Exemple

```jaguar
void main(string param) {
    i32 health = 100;

    jcc:assert(health > 0, "La vie doit être positive");
}
```

Si `condition` vaut `false`, le runtime produit un message d'erreur puis abandonne le programme.

---

# Entiers et utilitaires

## `jcc:abs_i32`

Retourne la valeur absolue d'un `i32`.

### Signature

```jaguar
i32 jcc:abs_i32(i32 value)
```

### Exemple

```jaguar
i32 x = jcc:abs_i32(-42);
// x == 42
```

---

## `jcc:min_i32`

Retourne le plus petit de deux entiers.

### Signature

```jaguar
i32 jcc:min_i32(i32 a, i32 b)
```

### Exemple

```jaguar
i32 x = jcc:min_i32(10, 25);
// x == 10
```

---

## `jcc:max_i32`

Retourne le plus grand de deux entiers.

### Signature

```jaguar
i32 jcc:max_i32(i32 a, i32 b)
```

### Exemple

```jaguar
i32 x = jcc:max_i32(10, 25);
// x == 25
```

---

## `jcc:clamp_i32`

Force une valeur à rester dans un intervalle.

### Signature

```jaguar
i32 jcc:clamp_i32(i32 value, i32 min, i32 max)
```

### Exemple

```jaguar
i32 health = jcc:clamp_i32(150, 0, 100);
// health == 100

health = jcc:clamp_i32(-10, 0, 100);
// health == 0
```

---

## `jcc:random_i32`

Retourne un entier pseudo-aléatoire compris entre `min` et `max`, bornes incluses.

### Signature

```jaguar
i32 jcc:random_i32(i32 min, i32 max)
```

### Exemple

```jaguar
i32 damage = jcc:random_i32(10, 25);
```

`damage` sera compris entre `10` et `25` inclus.

Si `max <= min`, la fonction retourne `min`.

> Cette fonction utilise le générateur pseudo-aléatoire classique de la libc. Elle ne doit pas être utilisée pour de la cryptographie ou pour générer des valeurs nécessitant une sécurité particulière.

---

# Temps

## `jcc:time_ms`

Retourne le temps fourni par le runtime sous forme de millisecondes depuis l'époque Unix.

### Signature

```jaguar
i64 jcc:time_ms()
```

### Exemple

```jaguar
i64 start = jcc:time_ms();

// ... travail ...

i64 end = jcc:time_ms();
i64 elapsed = end - start;

sys:print(elapsed);
```

### Attention

La valeur est basée sur `time()` du C et possède donc une résolution correspondant à cette horloge. `time_ms()` est une représentation en millisecondes du temps Unix ; ce n'est **pas** un chronomètre haute résolution.

Pour mesurer précisément des durées très courtes, cette fonction n'est donc pas adaptée.

---

# Mathématiques

Les fonctions mathématiques utilisent `f64`.

Les fonctions viennent principalement de `math.h`, mais sont exposées sous une forme Jaguar simple.

## `jcc:sqrt`

Racine carrée.

```jaguar
f64 result = jcc:sqrt(25.0);
// 5.0
```

Signature :

```jaguar
f64 jcc:sqrt(f64 value)
```

---

## `jcc:pow`

Puissance.

```jaguar
f64 result = jcc:pow(2.0, 8.0);
// 256.0
```

Signature :

```jaguar
f64 jcc:pow(f64 base, f64 exponent)
```

---

## `jcc:sin`, `jcc:cos`, `jcc:tan`

Fonctions trigonométriques.

```jaguar
f64 a = jcc:sin(1.0);
f64 b = jcc:cos(1.0);
f64 c = jcc:tan(1.0);
```

Signatures :

```jaguar
f64 jcc:sin(f64 value)
f64 jcc:cos(f64 value)
f64 jcc:tan(f64 value)
```

Les angles sont exprimés en **radians**, conformément aux fonctions C.

---

## `jcc:asin`, `jcc:acos`, `jcc:atan`

Fonctions trigonométriques inverses.

```jaguar
f64 a = jcc:asin(0.5);
f64 b = jcc:acos(0.5);
f64 c = jcc:atan(1.0);
```

Signatures :

```jaguar
f64 jcc:asin(f64 value)
f64 jcc:acos(f64 value)
f64 jcc:atan(f64 value)
```

Le résultat est exprimé en radians.

---

## `jcc:atan2`

Calcule l'angle à partir de deux coordonnées.

```jaguar
f64 angle = jcc:atan2(y, x);
```

Signature :

```jaguar
f64 jcc:atan2(f64 y, f64 x)
```

L'ordre est le même que pour `atan2` en C : `y` puis `x`.

---

## `jcc:floor`

Arrondi vers le bas.

```jaguar
f64 x = jcc:floor(4.9);
// 4.0
```

Signature :

```jaguar
f64 jcc:floor(f64 value)
```

---

## `jcc:ceil`

Arrondi vers le haut.

```jaguar
f64 x = jcc:ceil(4.1);
// 5.0
```

Signature :

```jaguar
f64 jcc:ceil(f64 value)
```

---

## `jcc:round`

Arrondi vers l'entier le plus proche selon l'implémentation actuelle de libjcc.

```jaguar
f64 x = jcc:round(4.6);
// 5.0
```

Signature :

```jaguar
f64 jcc:round(f64 value)
```

L'implémentation actuelle est équivalente à `floor(value + 0.5)`. Il faut donc garder à l'esprit son comportement particulier avec les nombres négatifs.

---

## `jcc:log`

Logarithme naturel (`ln`).

```jaguar
f64 x = jcc:log(10.0);
```

Signature :

```jaguar
f64 jcc:log(f64 value)
```

---

## `jcc:log10`

Logarithme en base 10.

```jaguar
f64 x = jcc:log10(1000.0);
// 3.0
```

Signature :

```jaguar
f64 jcc:log10(f64 value)
```

---

## `jcc:exp`

Calcule `e^x`.

```jaguar
f64 x = jcc:exp(1.0);
```

Signature :

```jaguar
f64 jcc:exp(f64 value)
```

---

## `jcc:fmod`

Calcule le reste flottant d'une division.

```jaguar
f64 r = jcc:fmod(10.5, 3.0);
```

Signature :

```jaguar
f64 jcc:fmod(f64 a, f64 b)
```

---

# Chaînes

Les fonctions de chaîne utilisent le type Jaguar `string`.

```jaguar
string text = "Hello Jaguar";
```

La bibliothèque cache les détails C (`char*`, `strlen`, `strcmp`, etc.).

---

## `jcc:string_length`

Retourne la longueur d'une chaîne.

```jaguar
i32 length = jcc:string_length("Hello");
// 5
```

Signature :

```jaguar
i32 jcc:string_length(string text)
```

---

## `jcc:string_equals`

Compare deux chaînes.

```jaguar
if (jcc:string_equals(name, "Oscar")) {
    sys:print("Bonjour !");
}
```

Signature :

```jaguar
bool jcc:string_equals(string a, string b)
```

La comparaison porte sur le **contenu** des chaînes, pas sur leur adresse mémoire.

---

## `jcc:string_compare`

Compare deux chaînes lexicographiquement, comme `strcmp`.

```jaguar
i32 result = jcc:string_compare("apple", "banana");
```

Signature :

```jaguar
i32 jcc:string_compare(string a, string b)
```

Le résultat suit la convention de `strcmp` :

- résultat `< 0` : `a` vient avant `b` ;
- résultat `== 0` : les chaînes sont égales ;
- résultat `> 0` : `a` vient après `b`.

La valeur exacte retournée n'est pas spécifiée comme étant `-1` ou `1`.

---

## `jcc:string_contains`

Vérifie si une chaîne contient une autre chaîne.

```jaguar
if (jcc:string_contains("Hello Jaguar", "Jaguar")) {
    sys:print("Trouvé");
}
```

Signature :

```jaguar
bool jcc:string_contains(string text, string needle)
```

---

## `jcc:string_starts_with`

Vérifie le préfixe d'une chaîne.

```jaguar
bool result = jcc:string_starts_with("JaguarCompiler", "Jaguar");
```

Signature :

```jaguar
bool jcc:string_starts_with(string text, string prefix)
```

---

## `jcc:string_ends_with`

Vérifie le suffixe d'une chaîne.

```jaguar
bool result = jcc:string_ends_with("main.ja", ".ja");
```

Signature :

```jaguar
bool jcc:string_ends_with(string text, string suffix)
```

---

## `jcc:string_concat`

Concatène deux chaînes et retourne une nouvelle chaîne.

```jaguar
string first = "Hello ";
string second = "Jaguar";

string result = jcc:string_concat(first, second);
sys:print(result);
```

Signature :

```jaguar
string jcc:string_concat(string a, string b)
```

---

## `jcc:string_substring`

Extrait une partie d'une chaîne.

```jaguar
string text = "Hello Jaguar";
string part = jcc:string_substring(text, 0, 5);

// "Hello"
```

Signature :

```jaguar
string jcc:string_substring(string text, i32 start, i32 length)
```

Si les indices dépassent la chaîne, la fonction limite automatiquement la zone demandée à la taille disponible.

Un `start` négatif est traité comme `0`, et une longueur négative comme `0`.

---

## `jcc:string_char_at`

Retourne la valeur numérique du caractère à un index donné.

```jaguar
string text = "Hello";
i32 c = jcc:string_char_at(text, 0);
```

Pour `"Hello"`, `c` correspond à la valeur du caractère `H`.

Signature :

```jaguar
i32 jcc:string_char_at(string text, i32 index)
```

Si l'index est invalide, la fonction retourne `-1`.

---

## `jcc:string_find`

Cherche une sous-chaîne et retourne sa position.

```jaguar
i32 index = jcc:string_find("Hello Jaguar", "Jaguar");
// 6
```

Signature :

```jaguar
i32 jcc:string_find(string text, string needle)
```

Si la sous-chaîne n'est pas trouvée, la fonction retourne `-1`.

---

## `jcc:string_to_upper`

Retourne une nouvelle chaîne convertie en majuscules.

```jaguar
string result = jcc:string_to_upper("hello");
// "HELLO"
```

Signature :

```jaguar
string jcc:string_to_upper(string text)
```

---

## `jcc:string_to_lower`

Retourne une nouvelle chaîne convertie en minuscules.

```jaguar
string result = jcc:string_to_lower("HELLO");
// "hello"
```

Signature :

```jaguar
string jcc:string_to_lower(string text)
```

Ces conversions reposent sur les fonctions de classification de caractères de la libc et sont donc adaptées principalement au texte ASCII/à la locale C utilisée par le programme.

---

# Conversions

## Chaîne → entier

### `jcc:string_to_i32`

```jaguar
i32 value = jcc:string_to_i32("1234");
```

Signature :

```jaguar
i32 jcc:string_to_i32(string text)
```

### `jcc:string_to_i64`

```jaguar
i64 value = jcc:string_to_i64("123456789");
```

Signature :

```jaguar
i64 jcc:string_to_i64(string text)
```

---

## Chaîne → flottant

### `jcc:string_to_f64`

```jaguar
f64 value = jcc:string_to_f64("3.14159");
```

Signature :

```jaguar
f64 jcc:string_to_f64(string text)
```

Ces fonctions utilisent les fonctions de conversion de la libc. Une chaîne qui ne représente pas correctement un nombre n'est pas signalée par une exception Jaguar ; la conversion suit le comportement de la fonction C sous-jacente.

---

## Entier → chaîne

### `jcc:i32_to_string`

```jaguar
i32 score = 150;
string text = jcc:i32_to_string(score);
```

Signature :

```jaguar
string jcc:i32_to_string(i32 value)
```

### `jcc:i64_to_string`

```jaguar
i64 score = 123456789;
string text = jcc:i64_to_string(score);
```

Signature :

```jaguar
string jcc:i64_to_string(i64 value)
```

---

## Flottant → chaîne

### `jcc:f64_to_string`

```jaguar
f64 pi = 3.1415926535;
string text = jcc:f64_to_string(pi);
```

Signature :

```jaguar
string jcc:f64_to_string(f64 value)
```

La conversion utilise actuellement une représentation proche de `%.17g`.

---

# Caractères

Les fonctions de caractères utilisent un `i32` pour représenter le caractère.

Exemple :

```jaguar
i32 c = jcc:string_char_at("Hello", 0);

if (jcc:is_upper(c)) {
    sys:print("La première lettre est une majuscule");
}
```

---

## `jcc:is_digit`

Vérifie si un caractère est un chiffre.

```jaguar
bool result = jcc:is_digit(53);
// true : 53 correspond à '5' en ASCII
```

Signature :

```jaguar
bool jcc:is_digit(i32 c)
```

---

## `jcc:is_alpha`

Vérifie si un caractère est alphabétique.

```jaguar
bool result = jcc:is_alpha(65);
```

Signature :

```jaguar
bool jcc:is_alpha(i32 c)
```

---

## `jcc:is_alnum`

Vérifie si un caractère est alphanumérique.

```jaguar
bool result = jcc:is_alnum(c);
```

Signature :

```jaguar
bool jcc:is_alnum(i32 c)
```

---

## `jcc:is_space`

Vérifie si un caractère est un espace ou un caractère blanc reconnu par la libc.

```jaguar
bool result = jcc:is_space(c);
```

Signature :

```jaguar
bool jcc:is_space(i32 c)
```

---

## `jcc:is_upper`

```jaguar
bool result = jcc:is_upper(c);
```

Signature :

```jaguar
bool jcc:is_upper(i32 c)
```

---

## `jcc:is_lower`

```jaguar
bool result = jcc:is_lower(c);
```

Signature :

```jaguar
bool jcc:is_lower(i32 c)
```

---

## `jcc:to_upper_char`

Convertit un caractère en majuscule.

```jaguar
i32 c = jcc:to_upper_char(97);
// 'A'
```

Signature :

```jaguar
i32 jcc:to_upper_char(i32 c)
```

---

## `jcc:to_lower_char`

Convertit un caractère en minuscule.

```jaguar
i32 c = jcc:to_lower_char(65);
// 'a'
```

Signature :

```jaguar
i32 jcc:to_lower_char(i32 c)
```

---

# Fichiers

Les opérations de fichiers exposées par `libjcc` sont volontairement simples.

Elles prennent des `string` Jaguar et retournent des `bool` lorsque l'opération peut réussir ou échouer.

Les objets `FILE*` ne sont pas exposés à Jaguar.

---

## `jcc:file_exists`

Vérifie qu'un fichier peut être ouvert en lecture binaire.

```jaguar
if (jcc:file_exists("save.dat")) {
    sys:print("Le fichier existe");
}
```

Signature :

```jaguar
bool jcc:file_exists(string path)
```

---

## `jcc:remove_file`

Supprime un fichier.

```jaguar
if (jcc:remove_file("old_save.dat")) {
    sys:print("Fichier supprimé");
}
```

Signature :

```jaguar
bool jcc:remove_file(string path)
```

Retourne `true` si la suppression réussit.

---

## `jcc:rename_file`

Renomme ou déplace un fichier selon les possibilités du système de fichiers.

```jaguar
bool success = jcc:rename_file("save.tmp", "save.dat");
```

Signature :

```jaguar
bool jcc:rename_file(string old_path, string new_path)
```

---

# Variables d'environnement

## `jcc:env_get`

Récupère la valeur d'une variable d'environnement.

```jaguar
string home = jcc:env_get("HOME");
```

Signature :

```jaguar
string jcc:env_get(string name)
```

Si la variable n'existe pas, la fonction retourne `null`.

Exemple :

```jaguar
string value = jcc:env_get("MY_GAME_CONFIG");

if (value != null) {
    sys:print(value);
}
```

Le nom des variables disponibles dépend du système d'exploitation et de l'environnement dans lequel le programme est lancé.

---

# Exemple complet

Voici un petit programme utilisant plusieurs parties de `libjcc` :

```jaguar
void main(string param) {
    string name = "Jaguar";

    // Strings
    string message = jcc:string_concat("Hello ", name);
    sys:print(message);

    if (jcc:string_contains(message, "Jag")) {
        sys:print("Le texte contient Jaguar.");
    }

    // Math
    f64 distance = jcc:sqrt(3.0 * 3.0 + 4.0 * 4.0);
    sys:print(distance);

    // Entiers
    i32 value = jcc:random_i32(0, 100);
    value = jcc:clamp_i32(value, 10, 90);

    // Conversion
    string value_text = jcc:i32_to_string(value);
    sys:print(value_text);

    // Caractères
    i32 first = jcc:string_char_at(name, 0);
    if (jcc:is_upper(first)) {
        sys:print("Le nom commence par une majuscule.");
    }

    // Fichier
    if (jcc:file_exists("save.dat")) {
        sys:print("Une sauvegarde existe.");
    }
}
```

---

# Combiner les fonctions

La bibliothèque est conçue pour être utilisée avec les autres fonctionnalités Jaguar, notamment `string` et `sys:print`.

Par exemple :

```jaguar
string player_name = "Oscar";
i32 score = 1250;

string score_text = jcc:i32_to_string(score);
string message = jcc:string_concat(player_name, " : ");
message = jcc:string_concat(message, score_text);

sys:print(message);
```

Ou pour traiter une entrée texte :

```jaguar
string input = "42";

i32 number = jcc:string_to_i32(input);
number = jcc:clamp_i32(number, 0, 100);

sys:print(jcc:i32_to_string(number));
```

---

# Fonctions non exposées

`libjcc` ne cherche volontairement pas à reproduire toute la libc.

Les fonctions qui nécessitent une manipulation directe de pointeurs, de buffers ou de structures C ne sont pas exposées dans cette API simplifiée.

Par exemple, les fonctions suivantes ne font pas partie de l'API `jcc` actuelle :

```text
malloc
calloc
realloc
free
memcpy
memmove
memcmp
memset
qsort
bsearch
strcpy
strncpy
strcat
strtok
strtol avec endptr exposé
strtod avec endptr exposé
fopen / fclose avec FILE*
fread / fwrite avec buffers
```

Cela est volontaire.

Jaguar possède ses propres abstractions (`string`, `list`, `map`, `container`, etc.) et `libjcc` doit rester simple à utiliser sans obliger le programmeur à manipuler la mémoire C directement.

Si une future API Jaguar a besoin d'une fonctionnalité bas niveau, elle pourra être ajoutée avec une abstraction Jaguar plutôt que d'exposer directement les pointeurs de la libc.

---

# C89

Les fonctions de `libjcc` sont également utilisables lorsque JaguarCC est lancé avec :

```text
--c89
```

Par exemple :

```text
python jcc.py main.ja --c89 -o game
```

Le runtime C généré respecte alors les contraintes nécessaires au mode C89 de JaguarCC.

---

# Génération du runtime

`libjcc` n'est pas une DLL ou une bibliothèque C externe que l'utilisateur doit installer.

Lorsqu'une fonction `jcc:*` est utilisée, JaguarCC génère automatiquement le code C nécessaire au runtime.

Par exemple :

```jaguar
void main(string param) {
    f64 x = jcc:sqrt(16.0);
    sys:print(x);
}
```

Le C généré contient les includes et le wrapper nécessaires, notamment :

```c
#include <math.h>
```

ainsi qu'une fonction interne équivalente à :

```c
static f64 _j_lib_sqrt(f64 v) {
    return sqrt(v);
}
```

Le programme Jaguar n'a donc pas besoin d'inclure lui-même `math.h`, `string.h`, `ctype.h`, `stdlib.h`, etc.

---

# Référence rapide

| Fonction | Retour | Description |
|---|---|---|
| `jcc:exit` | `void` | Termine le programme |
| `jcc:abort` | `void` | Abandonne le programme |
| `jcc:assert` | `void` | Vérifie une condition |
| `jcc:abs_i32` | `i32` | Valeur absolue |
| `jcc:min_i32` | `i32` | Minimum |
| `jcc:max_i32` | `i32` | Maximum |
| `jcc:clamp_i32` | `i32` | Limite une valeur |
| `jcc:random_i32` | `i32` | Entier pseudo-aléatoire |
| `jcc:time_ms` | `i64` | Temps Unix en millisecondes |
| `jcc:sqrt` | `f64` | Racine carrée |
| `jcc:pow` | `f64` | Puissance |
| `jcc:sin` | `f64` | Sinus |
| `jcc:cos` | `f64` | Cosinus |
| `jcc:tan` | `f64` | Tangente |
| `jcc:asin` | `f64` | Arcsinus |
| `jcc:acos` | `f64` | Arccosinus |
| `jcc:atan` | `f64` | Arctangente |
| `jcc:atan2` | `f64` | Arctangente à deux arguments |
| `jcc:floor` | `f64` | Arrondi inférieur |
| `jcc:ceil` | `f64` | Arrondi supérieur |
| `jcc:round` | `f64` | Arrondi |
| `jcc:log` | `f64` | Logarithme naturel |
| `jcc:log10` | `f64` | Logarithme base 10 |
| `jcc:exp` | `f64` | Exponentielle |
| `jcc:fmod` | `f64` | Reste flottant |
| `jcc:string_length` | `i32` | Longueur d'une chaîne |
| `jcc:string_equals` | `bool` | Compare deux chaînes |
| `jcc:string_compare` | `i32` | Comparaison lexicographique |
| `jcc:string_contains` | `bool` | Recherche une sous-chaîne |
| `jcc:string_starts_with` | `bool` | Teste un préfixe |
| `jcc:string_ends_with` | `bool` | Teste un suffixe |
| `jcc:string_concat` | `string` | Concatène deux chaînes |
| `jcc:string_substring` | `string` | Extrait une sous-chaîne |
| `jcc:string_char_at` | `i32` | Récupère un caractère |
| `jcc:string_find` | `i32` | Cherche une sous-chaîne |
| `jcc:string_to_upper` | `string` | Convertit en majuscules |
| `jcc:string_to_lower` | `string` | Convertit en minuscules |
| `jcc:string_to_i32` | `i32` | String → i32 |
| `jcc:string_to_i64` | `i64` | String → i64 |
| `jcc:string_to_f64` | `f64` | String → f64 |
| `jcc:i32_to_string` | `string` | i32 → String |
| `jcc:i64_to_string` | `string` | i64 → String |
| `jcc:f64_to_string` | `string` | f64 → String |
| `jcc:is_digit` | `bool` | Teste un chiffre |
| `jcc:is_alpha` | `bool` | Teste une lettre |
| `jcc:is_alnum` | `bool` | Teste lettre/chiffre |
| `jcc:is_space` | `bool` | Teste un espace |
| `jcc:is_upper` | `bool` | Teste une majuscule |
| `jcc:is_lower` | `bool` | Teste une minuscule |
| `jcc:to_upper_char` | `i32` | Caractère en majuscule |
| `jcc:to_lower_char` | `i32` | Caractère en minuscule |
| `jcc:file_exists` | `bool` | Teste l'existence d'un fichier |
| `jcc:remove_file` | `bool` | Supprime un fichier |
| `jcc:rename_file` | `bool` | Renomme un fichier |
| `jcc:env_get` | `string` | Lit une variable d'environnement |

---

# Version de l'API

Cette documentation correspond à l'API `jcc` actuellement implémentée dans `jcc.py`.

L'objectif de `libjcc` est de fournir une base standard suffisamment complète pour les programmes Jaguar courants tout en gardant l'accès à la libc derrière des abstractions Jaguar simples.
