#define M_PI 3.141


//si on utilise ces systemes sans avoir


//Le langage doit pouvoir etre ecrit sur une seule ligne

//Pas de directives d'include pour l'instant

//commentaires
/** commentaires multiligne */


//fonctions
void foo() {
  //contenu
}


//a et b sont nommés, faire un systeme de nommage (comme en python)
int add(int a, int b) {
  return a+b;
}


//fonction main
//string est un type par defaut, pour l'instant il ne peut pas faire grand chose, mais au moins
//on se fait pas chier avec des const char*
void main(string param) {
  //ne retourne rien
}


namespace my_namespace {
  //contenu
  int Foo() {}
}

//appel
my_namespace:Foo();


//equivalent de typedef struct en C, pas de struct C++!
struct my_struct_t {
  int int_val;
  float float_val;
}


//si ce n'est pas deja fait, ajoute les types standard comme bool, i64, i32, i16, i8, etc...

//pareil pour les pointeurs



//register decorateur pour factory native
@register @export class MyClass {
  //$ : public
  void $foo() {}
  void$ foo2() {} //marche aussi
  void$foo3() {} //marche aussi

  //le constructeur s'ecrit sans le $ mais il est bien public
  constr(){}
  destr(){}

  //% = protected
  int %protected_value;

  //rien pour private
  int public_value = 10;

  //le decorateur @exposed dans une classe permet d'acceder au membre depuis une string
  @exposed
  int exposed_value;
}

//creer un objet de cette classe
MyClass obj = MyClass();  //appelle le constructeur
obj.public_value = 30;  //modifie le membre
//utiliser la reflexion native (factory + membres exposés)
MyClass obj2 = factory:construct("MyClass");  //fonctionne nativement
//ces deux expressions sont equivalentes
obj.exposed_value = 10;
obj.GetMember("exposed_value") = 10;  //modifie le membre
//pour acceder à sa valeur
sys:print(obj.GetMember("exposed_value")); //affiche 10

//gestion de la mémoire
container<int> a = new int(3);  //permet l'ownership clair
//equivalent à : 
container<int> a => 3; //=> opérateur de creation et assignation auto
//acceder à la valeur : 
a.get();  //retourne 3
//pour des objets complexes : 
a->member = 3;  //on permet d'acceder directement via ->

//system lib
sys:print("hello %s", "world"); //print hello world, auto \n
sys:console:set_color("");
sys:console:reset_color();
sys:execute("program.exe", "C:/path_courant/...");
sys:fs:read("path/to/the/file.txt", "mode (r for example)");
sys:fs:write("path", "data", "mode (b for binary for example)");