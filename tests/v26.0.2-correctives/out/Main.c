#include <stdint.h>

#include <stdlib.h>

typedef struct BaseOver BaseOver;
typedef struct DerivedOver DerivedOver;

typedef unsigned char _jBool;
typedef int i32;
typedef double f64;
typedef struct _jString { size_t length; unsigned char literal; char data[]; } string;

/* Jaguar system library runtime (generated automatically). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

static string *string_alloc(size_t length) {
    string *s = (string *)malloc(sizeof(string) + length + 1);
    if (!s) return 0;
    s->length = length;
    s->data[length] = '\0';
    return s;
}
static string *string_from_cstr(const char *src) {
    string *s; size_t length;
    if (!src) src = "";
    length = strlen(src);
    s = string_alloc(length);
    if (!s) return 0;
    memcpy(s->data, src, length);
    s->literal = 0;
    return s;
}
typedef struct _jLiteralNode { string *s; struct _jLiteralNode *next; } _jLiteralNode;
static _jLiteralNode *_j_literal_head = 0;
static int _j_literal_atexit = 0;
static int _j_untrack_literal(string *self) { _jLiteralNode **pp; _jLiteralNode *n; if(!self)return 0; pp=&_j_literal_head; while(*pp){if((*pp)->s==self){n=*pp;*pp=n->next;free(n);return 1;}pp=&(*pp)->next;}return 0; }
static void _j_free_literals(void) { _jLiteralNode *n; _jLiteralNode *next; n=_j_literal_head; while(n){next=n->next;free(n->s);free(n);n=next;} _j_literal_head=0; }
static string *string_from_literal(const char *src) { string *s; _jLiteralNode *n; s=string_from_cstr(src); if(!s)return 0; s->literal=1; n=(_jLiteralNode*)malloc(sizeof(_jLiteralNode)); if(!n){free(s);return 0;} n->s=s;n->next=_j_literal_head;_j_literal_head=n; if(!_j_literal_atexit){atexit(_j_free_literals);_j_literal_atexit=1;} return s; }
static string *string_ctor(void) { return string_from_cstr(""); }
static void string_destr(string *self) {
    _jLiteralNode **pp; _jLiteralNode *n;
    if (!self) return;
    if (self->literal) {
        pp = &_j_literal_head;
        while (*pp) {
            if ((*pp)->s == self) {
                n = *pp; *pp = n->next; free(n); self->literal = 0; free(self); return;
            }
            pp = &(*pp)->next;
        }
        return;
    }
    free(self);
}
static i32 string_length(string *self) { return self ? (i32)self->length : 0; }
static _jBool string_empty(string *self) { return (!self || self->length == 0) ? 1 : 0; }
static _jBool string_equals(string *self, string *other) {
    if (!self || !other) return self == other;
    return strcmp(self->data ? self->data : "", other->data ? other->data : "") == 0;
}

static _jBool string_contains(string *self, string *needle) {
    if (!self || !needle) return 0;
    return strstr(self->data ? self->data : "", needle->data ? needle->data : "") != 0;
}
static _jBool string_starts_with(string *self, string *prefix) {
    if (!self || !prefix || prefix->length > self->length) return 0;
    return memcmp(self->data, prefix->data, prefix->length) == 0;
}
static _jBool string_ends_with(string *self, string *suffix) {
    if (!self || !suffix || suffix->length > self->length) return 0;
    return memcmp(self->data + self->length - suffix->length, suffix->data, suffix->length) == 0;
}
static string *string_concat(string *self, string *other) {
    size_t a = self ? self->length : 0, b = other ? other->length : 0;
    string *out = string_alloc(a + b);
    if (!out) return 0;
    if (a) memcpy(out->data, self->data, a);
    if (b) memcpy(out->data + a, other->data, b);
    out->data[out->length] = '\0';
    return out;
}
static string *string_substring(string *self, i32 start, i32 length) {
    size_t a, n; string *out;
    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr("");
    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;
    out = string_alloc(n); if (!out) return 0;
    memcpy(out->data, self->data + a, n); out->data[n] = '\0'; return out;
}
static i32 string_char_at(string *self, i32 index) {
    if (!self || index < 0 || (size_t)index >= self->length) return -1;
    return (unsigned char)self->data[index];
}
static string *string_transform_case(string *self, int upper) {
    size_t i; string *out;
    out = string_from_cstr(self ? self->data : ""); if (!out) return 0;
    for (i = 0; i < out->length; ++i) {
        unsigned char c = (unsigned char)out->data[i];
        if (upper && c >= 'a' && c <= 'z') out->data[i] = (char)(c - 'a' + 'A');
        if (!upper && c >= 'A' && c <= 'Z') out->data[i] = (char)(c - 'A' + 'a');
    } return out;
}
static string *string_to_upper(string *self) { return string_transform_case(self, 1); }
static string *string_to_lower(string *self) { return string_transform_case(self, 0); }

static void _j_sys_print_string(string *s) {
    printf("%s\n", (s && s->data) ? s->data : "");
}

static void _j_sys_print_int(int v) {
    printf("%d\n", v);
}

static void _j_sys_print_i8(signed char v) {
    printf("%d\n", (int)v);
}

static void _j_sys_print_u8(unsigned char v) {
    printf("%u\n", (unsigned int)v);
}

static void _j_sys_print_i16(short v) {
    printf("%d\n", (int)v);
}

static void _j_sys_print_u16(unsigned short v) {
    printf("%u\n", (unsigned int)v);
}

static void _j_sys_print_i32(int v) {
    printf("%d\n", v);
}

static void _j_sys_print_u32(unsigned int v) {
    printf("%u\n", v);
}

static void _j_sys_print_i64(long long v) {
    printf("%lld\n", v);
}

static void _j_sys_print_u64(unsigned long long v) {
    printf("%llu\n", v);
}

static void _j_sys_print_float(float v) {
    printf("%g\n", (double)v);
}

static void _j_sys_print_f32(float v) {
    printf("%g\n", (double)v);
}

static void _j_sys_print_f64(double v) {
    printf("%g\n", v);
}

static void _j_sys_print_bool(_jBool v) {
    printf("%s\n", v ? "true" : "false");
}

static void _j_sys_print_dynamic(void *data, const char *type) {
    if (!data || !type) { printf("<null>\n"); return; }
    if (!strcmp(type, "string")) { string *v=(string*)data; printf("%s\n", (v && v->data) ? v->data : ""); return; }
    if (!strcmp(type, "bool")) { printf("%s\n", *((_jBool*)data) ? "true" : "false"); return; }
    if (!strcmp(type, "f32") || !strcmp(type, "float")) { printf("%g\n", (double)*((float*)data)); return; }
    if (!strcmp(type, "f64")) { printf("%g\n", *((double*)data)); return; }
    if (!strcmp(type, "i8")) { printf("%d\n", (int)*((signed char*)data)); return; }
    if (!strcmp(type, "u8")) { printf("%u\n", (unsigned int)*((unsigned char*)data)); return; }
    if (!strcmp(type, "i16")) { printf("%d\n", (int)*((short*)data)); return; }
    if (!strcmp(type, "u16")) { printf("%u\n", (unsigned int)*((unsigned short*)data)); return; }
    if (!strcmp(type, "i32") || !strcmp(type, "int")) { printf("%d\n", *((int*)data)); return; }
    if (!strcmp(type, "u32")) { printf("%u\n", *((unsigned int*)data)); return; }
    if (!strcmp(type, "i64")) { printf("%lld\n", *((long long*)data)); return; }
    if (!strcmp(type, "u64")) { printf("%llu\n", *((unsigned long long*)data)); return; }
    fprintf(stderr, "Jaguar runtime error: cannot print a dynamic_list value of type '%s'\n", type);
    abort();
}

typedef struct _jReflectEntry { const char *name; void *ptr; const char *type_name; } _jReflectEntry;
typedef struct _jReflectMap { _jReflectEntry *entries; size_t count; } _jReflectMap;
typedef struct _jReflectVTable { const char *type_name; _jReflectEntry *(*get_member)(void*, const char*); } _jReflectVTable;
static _jReflectEntry *_j_reflect_find(void *obj, const char *name) { _jReflectVTable *vt; if (!obj || !name) return 0; vt=*(_jReflectVTable**)obj; return (vt&&vt->get_member)?vt->get_member(obj,name):0; }
static void *_j_reflect_get_member(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){fprintf(stderr,"Jaguar runtime error: member '%s' does not exist or is not exposed\n",name?name:"<null>"); return 0;} return e->ptr; }
static const char *_j_reflect_get_type(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); return e?e->type_name:0; }
static _jBool _j_reflect_member_exists(void *obj,const char *name) { return _j_reflect_find(obj,name)!=0; }

static void _j_reflect_set_member(void *obj,const char *name,const char *src_type,long long si,unsigned long long ui,double f,string *str,void *ptr) {
    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e||!e->ptr||!e->type_name||!src_type){fprintf(stderr,"Jaguar runtime error: member '%s' does not exist or is not exposed\n",name?name:"<null>");return;}
    if(!strcmp(e->type_name,"string")&&!strcmp(src_type,"string")){*(string**)e->ptr=str;return;}
    if(!strcmp(e->type_name,"i32")||!strcmp(e->type_name,"int")){*(int*)e->ptr=(int)(f && (!strcmp(src_type,"f32")||!strcmp(src_type,"f64")||!strcmp(src_type,"float")) ? f : si);return;}
    if(!strcmp(e->type_name,"u32")){*(unsigned int*)e->ptr=(unsigned int)ui;return;}
    if(!strcmp(e->type_name,"i64")){*(long long*)e->ptr=(long long)si;return;}
    if(!strcmp(e->type_name,"u64")){*(unsigned long long*)e->ptr=(unsigned long long)ui;return;}
    if(!strcmp(e->type_name,"f32")||!strcmp(e->type_name,"float")){*(float*)e->ptr=(float)f;return;}
    if(!strcmp(e->type_name,"f64")){*(double*)e->ptr=f;return;}
    if(!strcmp(e->type_name,"bool")){*(unsigned char*)e->ptr=(unsigned char)si;return;}
    fprintf(stderr,"Jaguar runtime error: cannot assign value of type '%s' to reflected member '%s' of type '%s'\n",src_type,name?name:"<null>",e->type_name);
}

static void *_j_factory_construct(string *name);

static _jBool _j_reflect_member_exists(void *obj, const char *name);

static void _j_reflect_set_member(void *obj, const char *name, const char *type_name, long long si, unsigned long long ui, double f, string *str, void *ptr);

static void _j_reflect_print(void *obj, const char *name);

typedef struct BaseOver_vtable BaseOver_vtable;
struct BaseOver {
    BaseOver_vtable *_vptr;
};
struct BaseOver_vtable {
    const char *type_name;
    _jReflectEntry *(*get_member)(void *self, const char *name);
    int32_t (*get_i32)(void *self, int32_t value);
    double (*get_f64)(void *self, double value);
};
static _jReflectEntry *BaseOver_get_member(void *obj, const char *name) {
    BaseOver *self = (BaseOver*)obj;
    return 0;
}
int32_t BaseOver_get_i32(BaseOver *self, int32_t value);
double BaseOver_get_f64(BaseOver *self, double value);
void BaseOver_destr(BaseOver *self);
BaseOver *BaseOver_new(void);
BaseOver *BaseOver_ctor(void);
static BaseOver_vtable BaseOver_vtable_instance = {
    "BaseOver",
    BaseOver_get_member,
    (int32_t (*)(void *, int32_t value))BaseOver_get_i32,
    (double (*)(void *, double value))BaseOver_get_f64,
};
int32_t BaseOver_get_i32(BaseOver *self, int32_t value) {
    return value + 10;
}
double BaseOver_get_f64(BaseOver *self, double value) {
    return value + 20.0;
}
BaseOver *BaseOver_ctor() {
    BaseOver *self = (BaseOver*)calloc(1, sizeof(BaseOver));
    if (!self) return 0;
    self->_vptr = &BaseOver_vtable_instance;
    return self;
}
void BaseOver_destr(BaseOver *self) {
}

typedef struct DerivedOver_vtable DerivedOver_vtable;
struct DerivedOver {
    DerivedOver_vtable *_vptr;
    BaseOver _base;
};
struct DerivedOver_vtable {
    const char *type_name;
    _jReflectEntry *(*get_member)(void *self, const char *name);
    int32_t (*get_i32)(void *self, int32_t value);
    double (*get_f64)(void *self, double value);
};
static _jReflectEntry *DerivedOver_get_member(void *obj, const char *name) {
    DerivedOver *self = (DerivedOver*)obj;
    return 0;
}
int32_t DerivedOver_get(DerivedOver *self, int32_t value);
void DerivedOver_destr(DerivedOver *self);
DerivedOver *DerivedOver_new(void);
DerivedOver *DerivedOver_ctor(void);
static DerivedOver_vtable DerivedOver_vtable_instance = {
    "DerivedOver",
    DerivedOver_get_member,
    (int32_t (*)(void *, int32_t value))DerivedOver_get,
    (double (*)(void *, double value))BaseOver_get_f64,
};
int32_t DerivedOver_get(DerivedOver *self, int32_t value) {
    return value + 100;
}
DerivedOver *DerivedOver_ctor() {
    DerivedOver *self = (DerivedOver*)calloc(1, sizeof(DerivedOver));
    if (!self) return 0;
    self->_vptr = &DerivedOver_vtable_instance;
    return self;
}
void DerivedOver_destr(DerivedOver *self) {
    BaseOver_destr(&self->_base);
}

int main(int _j_main_argc, char *_j_main_argv[]) {
    string *param = string_from_cstr((_j_main_argc > 1) ? _j_main_argv[1] : "");
    DerivedOver * object = DerivedOver_ctor();
    int32_t integer_result = object->_vptr->get_i32((void*)object, 2);
    double float_result = object->_vptr->get_f64((void*)object, 2.5);
    _j_sys_print_i32(integer_result);
    _j_sys_print_f64(float_result);
    if (object) DerivedOver_destr(object);
    return 0;
}

/* Jaguar native dynamic reflection / factory runtime. */
#include <string.h>
static void _j_reflect_print(void *obj,const char *name) {
    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){printf("<null>\n");return;}
    if(!strcmp(e->type_name,"string")){string *s=*(string**)e->ptr;printf("%s\n",(s&&s->data)?s->data:"");}
    else if(!strcmp(e->type_name,"bool")){printf("%s\n",*(unsigned char*)e->ptr?"true":"false");}
    else if(!strcmp(e->type_name,"i32")||!strcmp(e->type_name,"int")){printf("%d\n",*(int*)e->ptr);}
    else if(!strcmp(e->type_name,"u32")){printf("%u\n",*(unsigned int*)e->ptr);}
    else if(!strcmp(e->type_name,"i64")){printf("%lld\n",*(long long*)e->ptr);}
    else if(!strcmp(e->type_name,"u64")){printf("%llu\n",*(unsigned long long*)e->ptr);}
    else if(!strcmp(e->type_name,"f32")||!strcmp(e->type_name,"float")){printf("%g\n",(double)*(float*)e->ptr);}
    else if(!strcmp(e->type_name,"f64")){printf("%g\n",*(double*)e->ptr);}
    else printf("<object:%s>\n",e->type_name);
}
static void *_j_factory_construct(string *name) {
    if(!name||!name->data) {
        fprintf(stderr, "Jaguar runtime error: factory:construct() received a null class name\n");
        abort();
    }
    fprintf(stderr, "Jaguar runtime error: cannot construct class '%s': class is not registered\n", name->data);
    abort();
    return 0;
}
