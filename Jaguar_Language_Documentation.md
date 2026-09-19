# Jaguar — Documentation du langage

> Documentation de référence du langage Jaguar telle qu'implémentée par `jcc.py`.
>
> **Important :** cette documentation décrit l'implémentation actuelle du compilateur, pas une spécification future. Certaines fonctionnalités peuvent être volontairement limitées.

---

## 1. Présentation

**Jaguar** est un langage compilé qui est traduit en C par **JaguarCC (`jcc.py`)**, puis compilé avec GCC.

Le pipeline est :

```text
Code Jaguar (.ja)
       ↓
     Lexer
       ↓
     Parser
       ↓
    Resolver
       ↓
    CodeGen
       ↓
      C (.c)
       ↓
      GCC
       ↓
  Exécutable
```

Jaguar reprend volontairement plusieurs idées du C/C++ tout en simplifiant certains aspects :

- syntaxe proche du C ;
- types explicites ;
- classes et héritage ;
- surcharge de fonctions ;
- namespaces ;
- collections simples ;
- gestion automatique de certains objets ;
- réflexion limitée ;
- bibliothèque standard `jcc` ;
- génération de C compatible avec un mode C89.

---

# 2. Compiler un programme

## 2.1 Compilation directe

```bash
python jcc.py main.ja -o game
```

Le compilateur génère :

```text
game.c
game
```

Puis appelle GCC automatiquement.

Le nom de sortie **ne doit pas** se terminer par `.c` :

```bash
python jcc.py main.ja -o game
```

et non :

```bash
python jcc.py main.ja -o game.c
```

---

## 2.2 Générer uniquement le C

Sans `-o`, le C est écrit sur la sortie standard :

```bash
python jcc.py main.ja > main.c
```

---

## 2.3 Mode C89

```bash
python jcc.py main.ja --c89 -o game
```

En mode normal, les déclarations peuvent apparaître après des instructions, comme en C99+.

Avec `--c89`, Jaguar déplace les déclarations au début des blocs et laisse l'initialisation à son emplacement logique.

La sémantique Jaguar reste identique.

---

# 3. Syntaxe générale

Jaguar n'est **pas sensible aux retours à la ligne**.

Les blocs utilisent `{}` et les instructions se terminent généralement par `;`.

Exemple :

```jaguar
int main(string param) {
    int x = 10;
    int y = 20;

    if (x < y) {
        sys:print("x est plus petit");
    }

    return 0;
}
```

---

# 4. Commentaires

## Commentaire sur une ligne

```jaguar
// Ceci est un commentaire
int x = 10;
```

## Commentaire multiligne

```jaguar
/*
   Commentaire
   sur plusieurs lignes
*/
```

Les commentaires de documentation `/** ... */` sont également supprimés par le lexer.

---

# 5. Préprocesseur

Les directives `#define` sont conservées et transmises au C généré.

```jaguar
#define PI 3.14159265
#define GAME_VERSION 1
```

Elles peuvent notamment servir dans les expressions constantes.

```jaguar
#define START_HEALTH 100

int default_health = START_HEALTH;
```

Les macros ne sont pas des variables Jaguar et leur type n'est pas inféré par le compilateur Jaguar.

---

# 6. Types

## 6.1 Types principaux

| Jaguar | Alias | Type C approximatif |
|---|---|---|
| `void` | — | `void` |
| `int` | `i32` | `int` |
| `uint` | `u32` | `unsigned int` |
| `short` | `i16` | `short` |
| `ushort` | `u16` | `unsigned short` |
| `long` | `i64` | `long long` |
| `ulong` | `u64` | `unsigned long long` |
| `char` | `i8` | `signed char` |
| `uchar` | `u8` | `unsigned char` |
| `sbyte` | `i8` | `signed char` |
| `byte` | `u8` | `unsigned char` |
| `float` | `f32` | `float` |
| `double` | `f64` | `double` |
| `bool` | — | `_jBool` |
| `string` | — | objet string Jaguar |

Les alias sont normalisés par le compilateur. Par exemple :

```jaguar
int a = 10;
i32 b = 20;
```

utilisent tous deux le type logique `i32`.

---

# 7. Variables

## Déclaration

```jaguar
int x;
f64 speed;
bool alive;
string name;
```

## Initialisation

```jaguar
int x = 42;
f64 speed = 12.5;
bool alive = true;
string name = "Oscar";
```

Une variable locale peut être déclarée avec n'importe quel type connu.

---

# 8. `const`

`const` rend une variable ou un paramètre non modifiable.

```jaguar
const int max_health = 100;
```

Un paramètre peut également être `const` :

```jaguar
void print_value(const int value) {
    sys:print(value);
}
```

Les méthodes peuvent également être déclarées `const` :

```jaguar
int get_health() const {
    return health;
}
```

Une variable `const` locale doit être initialisée immédiatement.

```jaguar
const int x = 10;
```

---

# 9. `auto`

`auto` permet de déduire le type d'une variable locale depuis son initialisation.

```jaguar
auto x = 42;
auto value = 3.14;
auto name = "hello";
```

Une variable `auto` doit obligatoirement être initialisée.

```jaguar
auto x; // invalide
```

`auto` est destiné aux variables locales et aux constructions de boucle prévues par Jaguar.

---

# 10. Littéraux

## Entiers

```jaguar
0
42
-10
```

## Décimaux

```jaguar
3.14
0.5
10.0
```

## Booléens

```jaguar
true
false
```

## Strings

```jaguar
"Hello world"
```

---

# 11. `string`

`string` est le type chaîne natif de Jaguar.

```jaguar
string name = "Jaguar";
```

Il ne s'agit pas d'un simple `char*` exposé au programme Jaguar.

## Méthodes disponibles

### `length()`

```jaguar
int n = name.length();
```

### `empty()`

```jaguar
bool empty = name.empty();
```

### `equals()`

```jaguar
if (name.equals("Jaguar")) {
    sys:print("OK");
}
```

### `contains()`

```jaguar
bool found = name.contains("gua");
```

### `starts_with()`

```jaguar
bool result = name.starts_with("Jag");
```

### `ends_with()`

```jaguar
bool result = name.ends_with("ar");
```

### `concat()`

```jaguar
string full = name.concat("CC");
```

### `substring()`

```jaguar
string part = name.substring(0, 3);
```

### `char_at()`

```jaguar
i32 c = name.char_at(0);
```

Le résultat est le code du caractère, ou `-1` si l'index est invalide.

### `to_upper()` / `to_lower()`

```jaguar
string upper = name.to_upper();
string lower = name.to_lower();
```

---

# 12. Opérateurs

## Arithmétiques

```text
+   -   *   /   %
```

Exemple :

```jaguar
int result = (10 + 5) * 2;
```

## Comparaisons

```text
==  !=  <  >  <=  >=
```

Les comparaisons produisent un `bool`.

```jaguar
bool result = health <= 0;
```

## Logique

```text
&&  ||  !
```

Exemple :

```jaguar
if (alive && health > 0) {
    sys:print("vivant");
}
```

## Priorité

La priorité est proche du C :

```text
||
&&
== !=
< > <= >=
+ -
* / %
- !
```

Les parenthèses peuvent être utilisées pour rendre une expression explicite.

---

# 13. Casts

Jaguar utilise volontairement la syntaxe de cast C :

```jaguar
f64 value = (f64)10;
i32 integer = (i32)3.14;
```

La forme suivante n'est **pas** un cast Jaguar :

```jaguar
i32(3.14); // ce n'est pas la syntaxe de cast
```

---

# 14. Conversion implicite pour les surcharges

Le resolver peut utiliser des conversions numériques simples pour choisir une surcharge :

- entier → autre type entier ;
- entier → flottant ;
- flottant → autre type flottant.

Exemple :

```jaguar
void test(i32 value) {
    sys:print(value);
}

void test(f64 value) {
    sys:print(value);
}

test(10);
test(3.14);
```

Si plusieurs surcharges restent équivalentes, l'appel est considéré comme ambigu.

---

# 15. Fonctions

## Déclaration

```jaguar
int add(int a, int b) {
    return a + b;
}
```

## Appel

```jaguar
int result = add(10, 20);
```

## `void`

```jaguar
void say_hello() {
    sys:print("Hello");
}
```

---

# 16. Paramètres par défaut

Un paramètre peut avoir une valeur par défaut :

```jaguar
int add(int a, int b = 10) {
    return a + b;
}
```

Les deux appels suivants sont valides :

```jaguar
add(5);
add(5, 20);
```

---

# 17. Arguments nommés

Les arguments peuvent être transmis par nom :

```jaguar
int move(int x, int y, int speed = 1) {
    return x + y + speed;
}

move(y = 20, x = 10);
move(x = 10, y = 20, speed = 5);
```

Une fois qu'un argument nommé est utilisé, un argument positionnel ne peut plus suivre.

```jaguar
move(x = 10, 20); // invalide
```

Les fonctions intégrées `jcc:*` et `sys:*` n'acceptent pas les arguments nommés.

---

# 18. Prototypes

Une fonction peut être déclarée sans corps :

```jaguar
int add(int a, int b);
```

Puis définie plus loin :

```jaguar
int add(int a, int b) {
    return a + b;
}
```

Le prototype et la définition doivent avoir exactement la même signature.

Deux prototypes identiques ou deux définitions identiques provoquent une erreur.

---

# 19. Surcharge

Jaguar permet plusieurs fonctions de même nom avec des paramètres différents :

```jaguar
void print_value(i32 value) {
    sys:print(value);
}

void print_value(f64 value) {
    sys:print(value);
}
```

Le compilateur choisit la surcharge appropriée.

Le name mangling utilise les types des paramètres lorsque le nom est réellement surchargé.

---

# 20. `@extern`

`@extern` empêche le name mangling.

```jaguar
@extern
int my_native_function(int value);
```

Le nom C reste exactement `my_native_function`.

Cela permet notamment d'appeler des fonctions définies ailleurs dans le projet ou dans une bibliothèque native.

---

# 21. Fonction `main`

La forme spéciale recommandée est :

```jaguar
void main(string param) {
    sys:print("Hello");
}
```

ou une forme retournant un entier selon les fonctions supportées par le programme.

Jaguar traduit cette fonction vers un `main` C standard.

Le compilateur évite d'émettre un `main(string)` C non standard.

---

# 22. `return`

```jaguar
int square(int x) {
    return x * x;
}
```

Pour une fonction `void` :

```jaguar
void stop() {
    return;
}
```

---

# 23. Conditions

## `if`

```jaguar
if (health > 0) {
    sys:print("alive");
}
```

## `else`

```jaguar
if (health > 0) {
    sys:print("alive");
} else {
    sys:print("dead");
}
```

## `else if`

```jaguar
if (health > 75) {
    sys:print("high");
} else if (health > 25) {
    sys:print("medium");
} else {
    sys:print("low");
}
```

Les accolades sont obligatoires.

---

# 24. `while`

Le `while` Jaguar est volontairement différent du C : il ne prend **pas de condition**.

```jaguar
while {
    if (health <= 0) {
        break;
    }

    health = health - 1;
}
```

La sortie de boucle se fait avec `break` ou `return`.

La forme suivante est interdite :

```jaguar
while (health > 0) {
}
```

---

# 25. `break` et `continue`

```jaguar
while {
    if (value == 10) {
        break;
    }

    if (value == 5) {
        continue;
    }
}
```

Ils ne sont valides qu'à l'intérieur d'une boucle.

---

# 26. `for_loop`

Jaguar fournit une boucle numérique simplifiée :

```jaguar
int i = for_loop(0, 10) {
    sys:print(i);
}
```

La borne finale est **incluse**.

Donc :

```text
0 1 2 3 4 5 6 7 8 9 10
```

Si le début est supérieur à la fin, aucune itération n'est effectuée.

Le type de l'index doit être entier :

```text
int / i8 / u8 / i16 / u16 / i32 / u32 / i64 / u64
```

L'index est en lecture seule dans la boucle.

---

# 27. Portée des variables

Chaque bloc possède sa propre portée.

```jaguar
void test() {
    int x = 10;

    if (true) {
        int y = 20;
        sys:print(y);
    }

    // y n'existe plus ici
}
```

Deux blocs frères peuvent utiliser le même nom :

```jaguar
if (true) {
    int x = 10;
}

if (true) {
    int x = 20;
}
```

En revanche, masquer une variable visible depuis un scope englobant est interdit.

---

# 28. Variables globales

Une variable peut être déclarée au niveau global :

```jaguar
int max_health = 100;
f64 gravity = 9.81;
```

Un initialiseur global doit être une expression constante :

- littéral ;
- macro `#define` ;
- opération entre constantes.

Ceci est valide :

```jaguar
#define MAX_HEALTH 100
int max_health = MAX_HEALTH;
```

Ceci n'est pas valide comme initialisation globale :

```jaguar
int x = get_value();
```

Les variables globales doivent également être déclarées avant leur utilisation.

Les `list`, `map` et `container` ne sont actuellement pas utilisables comme variables globales.

---

# 29. `struct`

Les structures Jaguar sont des structures de données simples.

```jaguar
struct Vector2 {
    f32 x;
    f32 y;
}
```

Utilisation :

```jaguar
Vector2 position;
position.x = 10.0;
position.y = 20.0;
```

Elles sont générées comme des `typedef struct` C.

---

# 30. Classes

Jaguar possède un système de classes avec :

- champs ;
- méthodes ;
- constructeurs ;
- destructeurs ;
- héritage ;
- méthodes virtuelles ;
- `override` ;
- contrôle d'accès.

Exemple :

```jaguar
class Player {
    $int health = 100;

    void take_damage(int amount) {
        health = health - amount;
    }

    int get_health() const {
        return health;
    }
}
```

---

# 31. Contrôle d'accès des classes

Les membres sont privés par défaut.

## Public : `$`

```jaguar
class Player {
    $int health;
}
```

## Protected : `%`

```jaguar
class Player {
    %int health;
}
```

## Private

Sans marqueur :

```jaguar
class Player {
    int secret_value;
}
```

Le contrôle d'accès est vérifié par le compilateur.

---

# 32. Méthodes

```jaguar
class Player {
    $int health;

    void damage(int amount) {
        health = health - amount;
    }
}
```

Appel :

```jaguar
Player player = Player();
player.damage(10);
```

Une méthode possède implicitement un `self` dans le C généré.

---

# 33. `this`

Dans une classe, `this` désigne l'instance courante.

```jaguar
class Player {
    $int health;

    void reset() {
        this.health = 100;
    }
}
```

Dans le C généré, `this` correspond à `self`.

`this` n'est disponible que dans une classe.

---

# 34. Constructeur `constr`

```jaguar
class Player {
    $int health;

    constr(int initial_health) {
        health = initial_health;
    }
}
```

Création :

```jaguar
Player player = Player(100);
```

Le compilateur génère également l'allocation de l'objet.

---

# 35. Destructeur `destr`

```jaguar
class Player {
    destr() {
        sys:print("destroyed");
    }
}
```

Chaque classe possède un point d'entrée destructeur généré par le compilateur, même si aucun `destr()` n'est écrit.

Avec l'héritage, le destructeur de la classe de base est appelé automatiquement.

---

# 36. Héritage

La syntaxe actuelle est :

```jaguar
class Enemy {
    $int health;
}

class Zombie, Enemy {
    void attack() {
        health = health - 10;
    }
}
```

La classe dérivée contient la partie correspondant à sa classe de base.

---

# 37. Méthodes virtuelles

Une méthode peut être virtuelle :

```jaguar
class Enemy {
    virtual void attack() {
        sys:print("enemy attack");
    }
}
```

Une classe dérivée peut l'override :

```jaguar
class Zombie, Enemy {
    void attack() override {
        sys:print("zombie attack");
    }
}
```

`override` doit correspondre à une méthode `virtual` de la classe de base avec une signature exacte.

---

# 38. Méthodes `const`

```jaguar
class Player {
    $int health;

    int get_health() const {
        return health;
    }
}
```

Les paramètres peuvent également être `const`.

---

# 39. `new`

Jaguar possède l'expression `new` :

```jaguar
new Player(100)
```

Elle peut être utilisée dans les mécanismes d'ownership de `container`.

---

# 40. `container<T>`

`container<T>` représente une valeur dont le container possède la donnée.

```jaguar
container<int> value = new int(42);
```

Une syntaxe courte est disponible :

```jaguar
container<int> value => 42;
```

Lecture :

```jaguar
int x = value.get();
```

Pour une classe :

```jaguar
container<Player> player = new Player(100);
player.get().damage(10);
```

Le container détruit automatiquement l'objet qu'il possède.

Les `container` ne peuvent pas être indexés avec `[]`.

---

# 41. `list<T>`

`list<T>` est une collection homogène.

```jaguar
list<int> numbers = {1, 2, 3, 4};
```

Ajouter un élément :

```jaguar
numbers.push(5);
```

Lire un élément :

```jaguar
int value = numbers[2];
```

L'indexation est **en lecture seule**.

Cette syntaxe n'est pas autorisée :

```jaguar
numbers[2] = 10;
```

Pour modifier/ajouter des valeurs, utilisez les opérations prévues par la collection.

---

# 42. `map<K,V>`

`map<K,V>` est une collection clé/valeur.

```jaguar
map<string, int> scores = {
    "alice", 10,
    "bob", 20
};
```

Ajouter ou remplacer une entrée :

```jaguar
scores.emplace("charlie", 30);
```

Lire une valeur :

```jaguar
int score = scores["alice"];
```

L'indexation est en lecture seule :

```jaguar
scores["alice"] = 100; // invalide
```

Pour écrire dans la map, utilisez `emplace()`.

La clé `string` dispose d'une comparaison par contenu.

---

# 43. `pair<K,V>`

Une paire contient deux valeurs : `first` et `second`.

```jaguar
pair<string, int> result = {"score", 42};

sys:print(result.first);
sys:print(result.second);
```

`pair` est notamment utilisé par `loop_map`.

---

# 44. `dynamic_list`

`dynamic_list` permet de stocker plusieurs types dans une même collection.

```jaguar
dynamic_list values = {
    42,
    "hello",
    true,
    3.14
};
```

Ajouter :

```jaguar
values.push(123);
values.push("world");
```

Taille :

```jaguar
int count = values.size();
```

Type d'une valeur :

```jaguar
string type = values.type(1);
```

Accès brut :

```jaguar
auto value = values.get(0);
```

L'indexation est également disponible :

```jaguar
sys:print(values[0]);
```

Pour extraire une valeur primitive avec un type connu, un cast peut être utilisé :

```jaguar
i32 number = (i32)values[0];
f64 decimal = (f64)values[3];
```

Pour les objets/classes, le cast conserve le pointeur vers l'objet stocké.

---

# 45. Boucle `loop_list`

`loop_list` parcourt une `list<T>`.

```jaguar
list<int> numbers = {1, 2, 3, 4};

auto item = loop_list(numbers) {
    sys:print(item);
}
```

Pendant la boucle, la collection est considérée comme en lecture seule.

Ceci est donc interdit :

```jaguar
auto item = loop_list(numbers) {
    numbers.push(10); // interdit
}
```

`loop_list` ne fonctionne pas sur `dynamic_list`.

---

# 46. Boucle `loop_map`

`loop_map` parcourt une `map<K,V>` et fournit un `pair<K,V>`.

```jaguar
map<string, int> scores = {
    "alice", 10,
    "bob", 20
};

auto item = loop_map(scores) {
    sys:print(item.first);
    sys:print(item.second);
}
```

La map est en lecture seule pendant la boucle.

---

# 47. Signal de changement de variable

Jaguar possède une syntaxe `signal:` pour associer un bloc à une variable :

```jaguar
signal:health {
    sys:print("Health changed");
}
```

Cette fonctionnalité est destinée à associer une réaction aux modifications d'une variable.

> **Note :** le comportement exact dépend de la génération actuellement implémentée dans `jcc.py`. Cette syntaxe fait partie de l'AST du compilateur et doit être considérée comme une fonctionnalité spécifique de Jaguar, pas comme une construction C standard.

---

# 48. Namespaces

Les namespaces utilisent `:`.

```jaguar
namespace math {
    int add(int a, int b) {
        return a + b;
    }
}
```

Appel :

```jaguar
int value = math:add(10, 20);
```

Les namespaces peuvent être imbriqués :

```jaguar
namespace engine {
    namespace math {
        int add(int a, int b) {
            return a + b;
        }
    }
}
```

Appel :

```jaguar
engine:math:add(10, 20);
```

Le nom C généré est manglé pour éviter les collisions.

Les namespaces supportent actuellement les fonctions, structs, classes et namespaces imbriqués selon les règles du compilateur. Les variables globales directement dans un namespace ne sont pas supportées.

---

# 49. Appels de fonctions au niveau global

Une expression d'appel peut être placée au niveau global :

```jaguar
my_function();
```

Le compilateur peut alors générer l'appel correspondant dans le C produit lorsque le contexte le permet.

---

# 50. Bibliothèque `sys`

`sys` fournit les fonctions système directement intégrées à JaguarCC.

---

## `sys:print`

```jaguar
sys:print("Hello");
sys:print(42);
sys:print(3.14);
sys:print(true);
```

Types imprimables automatiquement :

- `string`
- `int`
- `i8`
- `u8`
- `i16`
- `u16`
- `i32`
- `u32`
- `i64`
- `u64`
- `float`
- `f32`
- `f64`
- `bool`
- certaines valeurs de `dynamic_list`.

Chaque appel imprime une valeur suivie d'un retour à la ligne.

---

# 51. Console

## `sys:console:set_color`

```jaguar
sys:console:set_color("\\033[31m");
sys:print("Red");
sys:console:reset_color();
```

La fonction attend une séquence ANSI.

## `sys:console:reset_color`

```jaguar
sys:console:reset_color();
```

---

# 52. Exécution de programme

```jaguar
int result = sys:execute("program", ".");
```

Le deuxième argument représente le répertoire de travail.

Le résultat correspond au code retourné par l'exécution système.

---

# 53. Système de fichiers

## Lire un fichier

```jaguar
string data = sys:fs:read("save.txt");
```

## Écrire un fichier

```jaguar
sys:fs:write("save.txt", "hello");
```

Ces fonctions utilisent l'API fichier C en interne sans exposer `FILE*` au langage Jaguar.

---

# 54. Bibliothèque standard `jcc`

`jcc` est la bibliothèque standard simplifiée de JaguarCC.

Elle expose des fonctions inspirées de la libc, mais adaptées aux types et conventions Jaguar.

Les pointeurs et les API libc trop bas niveau ne sont volontairement pas exposés directement.

---

## 54.1 Processus

### `jcc:exit`

```jaguar
jcc:exit(0);
```

Termine le programme avec le code fourni.

### `jcc:abort`

```jaguar
jcc:abort();
```

Arrête immédiatement le programme.

---

## 54.2 Entiers

### `jcc:abs_i32`

```jaguar
i32 x = jcc:abs_i32(-42);
```

### `jcc:min_i32`

```jaguar
i32 x = jcc:min_i32(10, 20);
```

### `jcc:max_i32`

```jaguar
i32 x = jcc:max_i32(10, 20);
```

### `jcc:clamp_i32`

```jaguar
i32 x = jcc:clamp_i32(value, 0, 100);
```

### `jcc:random_i32`

```jaguar
i32 x = jcc:random_i32(0, 100);
```

### `jcc:time_ms`

```jaguar
i64 now = jcc:time_ms();
```

Retourne un temps en millisecondes.

### `jcc:assert`

```jaguar
jcc:assert(health >= 0, "health must not be negative");
```

---

# 55. Fonctions mathématiques `jcc`

Toutes les fonctions suivantes utilisent principalement `f64`.

| Fonction | Signature |
|---|---|
| `sqrt` | `f64 -> f64` |
| `pow` | `f64, f64 -> f64` |
| `sin` | `f64 -> f64` |
| `cos` | `f64 -> f64` |
| `tan` | `f64 -> f64` |
| `asin` | `f64 -> f64` |
| `acos` | `f64 -> f64` |
| `atan` | `f64 -> f64` |
| `atan2` | `f64, f64 -> f64` |
| `floor` | `f64 -> f64` |
| `ceil` | `f64 -> f64` |
| `round` | `f64 -> f64` |
| `log` | `f64 -> f64` |
| `log10` | `f64 -> f64` |
| `exp` | `f64 -> f64` |
| `fmod` | `f64, f64 -> f64` |

Exemple :

```jaguar
f64 distance = jcc:sqrt(x * x + y * y);
f64 angle = jcc:atan2(y, x);
f64 power = jcc:pow(2.0, 8.0);
```

---

# 56. Fonctions string de `jcc`

`jcc` expose également des wrappers simples autour des opérations de chaînes.

```jaguar
string a = "Hello";
string b = " World";

int length = jcc:string_length(a);
bool same = jcc:string_equals(a, b);
string result = jcc:string_concat(a, b);
```

Fonctions :

```text
string_length
string_equals
string_compare
string_contains
string_starts_with
string_ends_with
string_concat
string_substring
string_char_at
string_find
string_to_upper
string_to_lower
```

Exemple :

```jaguar
if (jcc:string_contains("Hello world", "world")) {
    sys:print("found");
}
```

---

# 57. Conversions de chaînes

String → nombre :

```jaguar
i32 a = jcc:string_to_i32("42");
i64 b = jcc:string_to_i64("100000");
f64 c = jcc:string_to_f64("3.14");
```

Nombre → string :

```jaguar
string a = jcc:i32_to_string(42);
string b = jcc:i64_to_string(100000);
string c = jcc:f64_to_string(3.14);
```

---

# 58. Fonctions caractères

Les fonctions inspirées de `ctype.h` utilisent des codes de caractères entiers.

```jaguar
bool digit = jcc:is_digit('0');
```

Fonctions disponibles :

```text
is_digit
is_alpha
is_alnum
is_space
is_upper
is_lower
to_upper_char
to_lower_char
```

Elles peuvent être utilisées sur le résultat de `string.char_at()`.

Exemple :

```jaguar
i32 c = name.char_at(0);
if (jcc:is_alpha(c)) {
    sys:print("letter");
}
```

---

# 59. Fichiers et environnement avec `jcc`

## `file_exists`

```jaguar
bool exists = jcc:file_exists("save.dat");
```

## `remove_file`

```jaguar
bool success = jcc:remove_file("save.dat");
```

## `rename_file`

```jaguar
bool success = jcc:rename_file("old.txt", "new.txt");
```

## `env_get`

```jaguar
string home = jcc:env_get("HOME");
```

Ces fonctions évitent de manipuler directement `FILE*`, `char*`, etc.

---

# 60. Réflexion

Jaguar possède un système de réflexion volontairement limité.

Une classe peut être enregistrée avec `@register` :

```jaguar
@register
class Player {
    $int health = 100;
}
```

Un champ public peut être exposé avec `@exposed` :

```jaguar
@register
class Player {
    @exposed
    $int health = 100;
}
```

`@exposed` ne peut être utilisé que sur un champ public.

---

# 61. `factory:construct`

Une classe enregistrée peut être construite dynamiquement avec son nom :

```jaguar
string class_name = "Player";
auto object = factory:construct(class_name);
```

La classe doit être enregistrée avec `@register`.

Le nom est résolu à l'exécution.

Si la classe n'est pas enregistrée, le runtime produit une erreur.

---

# 62. `GetMember`

Un membre exposé peut être récupéré dynamiquement :

```jaguar
string member = "health";
int health = (int)object.GetMember(member);
```

Le nom du membre est une `string`.

Si le membre n'existe pas ou n'est pas exposé, le runtime affiche une erreur.

Le cast est important pour obtenir une valeur typée.

---

# 63. `MemberExists`

Avant un accès dynamique :

```jaguar
string name = "health";

if (object.MemberExists(name)) {
    int health = (int)object.GetMember(name);
}
```

Cela permet de vérifier si un membre est exposé.

---

# 64. `SetMember`

Un membre exposé peut être modifié dynamiquement :

```jaguar
object.SetMember("health", 50);
```

Les valeurs primitives et `string` sont prises en charge par le runtime de réflexion.

---

# 65. Exemple complet de réflexion

```jaguar
@register
class Enemy {
    @exposed
    $int health = 100;

    $string name = "Enemy";
}

void main(string param) {
    string class_name = "Enemy";
    auto enemy = factory:construct(class_name);

    if (enemy.MemberExists("health")) {
        sys:print((int)enemy.GetMember("health"));
        enemy.SetMember("health", 25);
        sys:print((int)enemy.GetMember("health"));
    }
}
```

Seuls les membres marqués `@exposed` sont accessibles via la réflexion.

---

# 66. Attributs disponibles

Les attributs actuellement reconnus par le compilateur sont :

```text
@extern
@register
@exposed
```

Leur utilisation dépend du contexte :

| Attribut | Utilisation |
|---|---|
| `@extern` | fonction |
| `@register` | classe |
| `@exposed` | champ public de classe |

Un attribut inconnu produit une erreur de compilation.

---

# 67. Création de collections avec `{}`

Les accolades peuvent créer des littéraux de collection.

Liste :

```jaguar
list<int> values = {1, 2, 3};
```

Map :

```jaguar
map<string, int> values = {
    "one", 1,
    "two", 2
};
```

Pair :

```jaguar
pair<string, int> value = {"score", 42};
```

`dynamic_list` :

```jaguar
dynamic_list values = {1, "hello", true};
```

---

# 68. Indexation

`[]` est disponible sur certaines collections.

```jaguar
int x = numbers[0];
int score = scores["player"];
auto value = values[0];
```

Elle est volontairement en lecture seule.

Les `container<T>` ne sont pas indexables.

---

# 69. Gestion mémoire

Jaguar ne donne volontairement pas accès à toute la libc mémoire directement.

Le runtime gère notamment :

- les strings ;
- les classes ;
- les containers ;
- les listes ;
- les maps ;
- les dynamic lists.

Les structures internes utilisent C `malloc`, `calloc`, `realloc`, `free`, etc., mais ces pointeurs ne sont pas exposés comme API Jaguar générale.

Cela permet de conserver une syntaxe Jaguar plus sûre et plus simple.

---

# 70. Fonctions libc volontairement non exposées

Le compilateur connaît plusieurs noms libc afin d'éviter les collisions avec les fonctions Jaguar.

Par exemple, les noms suivants sont réservés lorsqu'ils sont utilisés comme fonctions Jaguar ordinaires :

```text
malloc
free
memcpy
memset
printf
scanf
fopen
fclose
strlen
strcmp
strcpy
qsort
rand
srand
system
...
```

L'objectif est d'éviter qu'une fonction Jaguar génère accidentellement un symbole C entrant en collision avec la libc.

Lorsqu'une fonctionnalité libc est utile, elle doit idéalement être exposée par une API Jaguar `jcc:*` adaptée plutôt que par les pointeurs C bruts.

---

# 71. Name mangling

Jaguar génère des noms C compatibles avec les namespaces et la surcharge.

Une fonction simple :

```jaguar
int add(int a, int b) {
    return a + b;
}
```

reste généralement `add` côté C lorsqu'elle n'est pas surchargée.

Une fonction dans un namespace :

```jaguar
namespace math {
    int add(int a, int b) {
        return a + b;
    }
}
```

est manglée pour éviter les collisions, par exemple sous une forme du type :

```text
math_add
```

Une surcharge utilise également les types des paramètres dans son nom C.

---

# 72. Résolution des appels

Lorsqu'un appel est rencontré, Jaguar recherche :

1. le namespace et le nom ;
2. les fonctions candidates ;
3. les paramètres par défaut ;
4. les arguments nommés ;
5. le type des arguments ;
6. les conversions numériques autorisées ;
7. la surcharge la plus adaptée.

Un appel ambigu provoque une erreur.

---

# 73. Fonctions natives inconnues

Pour appeler une fonction C externe, la forme prévue est `@extern`.

```jaguar
@extern
int native_function(int value);
```

Cela évite d'exposer arbitrairement toutes les fonctions de la libc au langage.

---

# 74. Compatibilité C

Jaguar génère du C destiné principalement à GCC et à des compilateurs C modernes.

Le mode :

```bash
--c89
```

demande au générateur de produire une organisation compatible avec C89.

Le runtime évite notamment d'utiliser `_Bool` pour `bool` et génère son propre type `_jBool`.

---

# 75. Ce que Jaguar n'expose volontairement pas

Le langage actuel évite plusieurs fonctionnalités bas niveau du C/C++ :

- pointeurs Jaguar génériques ;
- arithmétique de pointeurs ;
- `malloc`/`free` directement depuis le code Jaguar ;
- `FILE*` ;
- `memcpy` et autres primitives mémoire directement ;
- templates C++ ;
- fonctionnalités C++ complexes ;
- lambdas ;
- exceptions ;
- héritage multiple.

Les fonctionnalités nécessitant ces mécanismes peuvent être implémentées dans le runtime C ou ajoutées plus tard au langage.

---

# 76. Exemple complet

Voici un petit programme utilisant plusieurs fonctionnalités du langage :

```jaguar
#define MAX_HEALTH 100

@register
class Player {
    @exposed
    $int health = MAX_HEALTH;

    constr(int initial_health = MAX_HEALTH) {
        health = initial_health;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}

int add(int a, int b = 0) {
    return a + b;
}

void main(string param) {
    Player player = Player(100);

    list<int> values = {10, 20, 30};

    auto item = loop_list(values) {
        sys:print(item);
    }

    player.damage(25);

    sys:print(player.health);

    if (player.alive()) {
        sys:print("Player alive");
    }

    f64 distance = jcc:sqrt(3.0 * 3.0 + 4.0 * 4.0);
    sys:print(distance);

    string text = jcc:i32_to_string(add(10, b = 20));
    sys:print(text);
}
```

---

# 77. Exemple : petit programme de jeu

```jaguar
class Player {
    $f32 x = 0.0;
    $f32 y = 0.0;
    $int health = 100;

    void move(f32 dx, f32 dy) {
        x = x + dx;
        y = y + dy;
    }

    void damage(int amount) {
        health = health - amount;
    }

    bool alive() const {
        return health > 0;
    }
}

void main(string param) {
    Player player = Player();

    int i = for_loop(0, 4) {
        player.move(1.0, 0.5);
        sys:print(i);
    }

    player.damage(20);

    if (player.alive()) {
        sys:print("Player is alive");
    }

    sys:print(player.x);
    sys:print(player.y);
}
```

---

# 78. Résumé syntaxique

```text
// commentaire
/* commentaire */

#define NAME VALUE

const int x = 10;
auto y = 20;

int add(int a, int b) {
    return a + b;
}

int add(int a, int b);

if (condition) {
} else if (other) {
} else {
}

while {
    break;
    continue;
}

int i = for_loop(0, 10) {
}

struct Vector2 {
    f32 x;
    f32 y;
}

class Player {
    $int health;
    %int protected_value;
    int private_value;

    constr() {
    }

    virtual void update() {
    }

    void update_child() override {
    }

    destr() {
    }
}

namespace game {
    int start() {
        return 0;
    }
}

list<int> values = {1, 2, 3};
map<string, int> scores = {"a", 10};
pair<string, int> result = {"score", 42};
dynamic_list data = {42, "hello", true};
container<int> value => 42;

sys:print("Hello");
jcc:sqrt(25.0);
```

---

# 79. Référence rapide

## Types

```text
void
int / i32
uint / u32
short / i16
ushort / u16
long / i64
ulong / u64
char / i8
uchar / u8
sbyte / i8
byte / u8
float / f32
double / f64
bool
string
list<T>
map<K,V>
pair<K,V>
container<T>
dynamic_list
```

## Contrôle

```text
if / else
while
for_loop
break
continue
return
```

## Classes

```text
class
constr
destr
virtual
override
this
$
%
const
```

## Namespaces

```text
namespace
namespace:function()
```

## Attributs

```text
@extern
@register
@exposed
```

## Collections

```text
list.push()
list[index]

map.emplace()
map[key]

pair.first
pair.second

container.get()

 dynamic_list.push()
 dynamic_list.get()
 dynamic_list.type()
 dynamic_list.size()
 dynamic_list[index]

loop_list()
loop_map()
```

## Système

```text
sys:print()
sys:console:set_color()
sys:console:reset_color()
sys:execute()
sys:fs:read()
sys:fs:write()
```

## Standard `jcc`

```text
jcc:exit()
jcc:abort()
jcc:abs_i32()
jcc:min_i32()
jcc:max_i32()
jcc:clamp_i32()
jcc:random_i32()
jcc:time_ms()
jcc:assert()

jcc:sqrt()
jcc:pow()
jcc:sin()
jcc:cos()
jcc:tan()
jcc:asin()
jcc:acos()
jcc:atan()
jcc:atan2()
jcc:floor()
jcc:ceil()
jcc:round()
jcc:log()
jcc:log10()
jcc:exp()
jcc:fmod()

jcc:string_length()
jcc:string_equals()
jcc:string_compare()
jcc:string_contains()
jcc:string_starts_with()
jcc:string_ends_with()
jcc:string_concat()
jcc:string_substring()
jcc:string_char_at()
jcc:string_find()
jcc:string_to_upper()
jcc:string_to_lower()

jcc:string_to_i32()
jcc:string_to_i64()
jcc:string_to_f64()
jcc:i32_to_string()
jcc:i64_to_string()
jcc:f64_to_string()

jcc:is_digit()
jcc:is_alpha()
jcc:is_alnum()
jcc:is_space()
jcc:is_upper()
jcc:is_lower()
jcc:to_upper_char()
jcc:to_lower_char()

jcc:file_exists()
jcc:remove_file()
jcc:rename_file()
jcc:env_get()
```

---

# 80. Philosophie du langage

Jaguar cherche à garder un compromis entre :

- **simplicité d'utilisation** ;
- **syntaxe proche du C/C++** ;
- **performances d'un langage compilé** ;
- **contrôle explicite des types** ;
- **fonctionnalités modernes pratiques** ;
- **runtime minimal** ;
- **interopérabilité avec le C**.

Le compilateur s'occupe autant que possible des détails bas niveau tout en laissant les fonctionnalités essentielles du langage explicites.

---

# 81. Statut des fonctionnalités

Cette documentation correspond au comportement actuellement présent dans `jcc.py`.

Les points à considérer comme particulièrement spécifiques à l'implémentation actuelle sont :

- la forme du `while` sans condition ;
- `for_loop` avec borne finale incluse ;
- les collections sans templates C++ ;
- l'interdiction de modifier une collection pendant `loop_list` / `loop_map` ;
- les `container<T>` ;
- `dynamic_list` ;
- le système `@register` / `@exposed` / `factory:construct` ;
- les fonctions `sys:*` ;
- la bibliothèque `jcc:*` ;
- la stratégie de génération C89 ;
- le name mangling et la résolution de surcharge.

Pour toute fonctionnalité non décrite ici, il faut se référer au comportement réel de `jcc.py` plutôt que supposer qu'elle est héritée du C ou du C++.
